//! Stream an LZ4-frame file as lines without decompressing it to disk.
//!
//! Hyperliquid's S3 archives (`replica_cmds`, `node_fills_by_block`, L2
//! snapshots) are LZ4 frames of JSON lines.

use std::fs::File;
use std::io::{self, BufRead, BufReader, Read};
use std::path::Path;
use std::str;

use lz4_flex::frame::FrameDecoder;

/// Line reader over any LZ4-frame stream. The decoder is itself a `BufRead` over
/// each decompressed block, so wrapping it in a `BufReader` would only add a copy.
pub fn reader<R: Read>(inner: R) -> FrameDecoder<R> {
    FrameDecoder::new(inner)
}

/// Line reader over an LZ4-frame file.
pub fn open(path: &Path) -> io::Result<FrameDecoder<BufReader<File>>> {
    Ok(reader(BufReader::new(File::open(path)?)))
}

/// Call `f(line_index, line)` for each line, with the trailing `\n` or `\r\n` stripped.
/// Returns the number of lines read.
///
/// Lines are passed straight out of the reader's buffer; only a line that straddles
/// two buffer fills is copied. A line that is not UTF-8 is an `InvalidData` error.
pub fn for_each_line<R: BufRead>(mut r: R, mut f: impl FnMut(u64, &str)) -> io::Result<u64> {
    let mut i = 0;
    let mut emit = |line: &[u8]| {
        let line = line.strip_suffix(b"\r").unwrap_or(line);
        f(i, str::from_utf8(line).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?);
        i += 1;
        io::Result::Ok(())
    };
    let mut carry = Vec::new();
    loop {
        let buf = r.fill_buf()?;
        if buf.is_empty() {
            break;
        }
        let mut rest = buf;
        while let Some(nl) = memchr::memchr(b'\n', rest) {
            if carry.is_empty() {
                emit(&rest[..nl])?;
            } else {
                carry.extend_from_slice(&rest[..nl]);
                emit(&carry)?;
                carry.clear();
            }
            rest = &rest[nl + 1..];
        }
        carry.extend_from_slice(rest);
        let n = buf.len();
        r.consume(n);
    }
    if !carry.is_empty() {
        emit(&carry)?;
    }
    Ok(i)
}

/// Block height of line `i` (0-based) of a `replica_cmds` file named after
/// `start`: `start + i + 1` (the SDK's `REPLICA_CMD_BATCH_SIZE` layout; the
/// first line of `100` is block 101). Confirm on the first file of every probe.
pub fn replica_height(start: u64, line_index: u64) -> u64 {
    start + line_index + 1
}

#[cfg(test)]
mod tests {
    use super::*;
    use lz4_flex::frame::FrameEncoder;
    use std::io::Write;

    #[test]
    fn roundtrip_lines() {
        let mut enc = FrameEncoder::new(Vec::new());
        for i in 0..1000 {
            writeln!(enc, "{{\"i\":{i}}}").unwrap();
        }
        write!(enc, "last-no-newline").unwrap();
        let bytes = enc.finish().unwrap();
        let mut got = Vec::new();
        let n = for_each_line(reader(&bytes[..]), |i, l| got.push((i, l.to_string()))).unwrap();
        assert_eq!(n, 1001);
        assert_eq!(got[0], (0, "{\"i\":0}".to_string()));
        assert_eq!(got[999].1, "{\"i\":999}");
        assert_eq!(got[1000].1, "last-no-newline");
    }

    #[test]
    fn lines_straddling_refills() {
        // Reference: the old `read_line` loop, which stripped one `\n` and then one `\r`.
        let text = format!("a\r\n\nbb\rb\r\r\n{}\n\u{e9}t\u{e9}\nlast\r", "x".repeat(300));
        let want: Vec<&str> = text
            .split_inclusive('\n')
            .map(|l| l.strip_suffix('\n').unwrap_or(l))
            .map(|l| l.strip_suffix('\r').unwrap_or(l))
            .collect();
        for cap in [1, 2, 3, 7, 64, 1 << 12] {
            let mut got = Vec::new();
            let n = for_each_line(BufReader::with_capacity(cap, text.as_bytes()), |i, l| {
                assert_eq!(i as usize, got.len());
                got.push(l.to_string());
            })
            .unwrap();
            assert_eq!(got, want, "capacity {cap}");
            assert_eq!(n as usize, want.len());
        }
        let err = for_each_line(&b"ok\n\xff\n"[..], |_, _| {}).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::InvalidData);
    }

    #[test]
    fn height_arithmetic() {
        assert_eq!(replica_height(100, 0), 101);
        assert_eq!(replica_height(1_191_310_000, 9_999), 1_191_320_000);
    }
}
