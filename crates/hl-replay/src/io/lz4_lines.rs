//! Stream an LZ4-frame file as lines without decompressing it to disk.
//!
//! Hyperliquid's S3 archives (`replica_cmds`, `node_fills_by_block`, L2
//! snapshots) are LZ4 frames of JSON lines.

use std::fs::File;
use std::io::{self, BufRead, BufReader, Read};
use std::path::Path;

use lz4_flex::frame::FrameDecoder;

const BUF: usize = 1 << 20;

/// Buffered line reader over any LZ4-frame stream.
pub fn reader<R: Read>(inner: R) -> BufReader<FrameDecoder<R>> {
    BufReader::with_capacity(BUF, FrameDecoder::new(inner))
}

/// Buffered line reader over an LZ4-frame file.
pub fn open(path: &Path) -> io::Result<BufReader<FrameDecoder<File>>> {
    Ok(reader(File::open(path)?))
}

/// Call `f(line_index, line)` for each line, reusing one buffer. The trailing
/// newline is stripped. Returns the number of lines read.
pub fn for_each_line<R: BufRead>(mut r: R, mut f: impl FnMut(u64, &str)) -> io::Result<u64> {
    let mut buf = String::with_capacity(1 << 16);
    let mut i = 0u64;
    loop {
        buf.clear();
        if r.read_line(&mut buf)? == 0 {
            return Ok(i);
        }
        let line = buf.strip_suffix('\n').unwrap_or(&buf);
        let line = line.strip_suffix('\r').unwrap_or(line);
        f(i, line);
        i += 1;
    }
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
    fn height_arithmetic() {
        assert_eq!(replica_height(100, 0), 101);
        assert_eq!(replica_height(1_191_310_000, 9_999), 1_191_320_000);
    }
}
