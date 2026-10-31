//! Python bindings for `hl-replay` (built with maturin; `import hl_replay`).
//!
//! Exposes the book so Python tests and notebooks can drive it. Python input is
//! untrusted, so it is checked here and raised as `ValueError`; the core book
//! asserts instead. The `replay(path, coin) -> pyarrow.Table` entry point lands
//! with the Phase 1 readers.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use replay::{Book as RBook, Side};

fn side(s: &str) -> PyResult<Side> {
    Side::from_hl(s).ok_or_else(|| PyValueError::new_err(format!("side must be 'B' or 'A', got {s:?}")))
}

/// Order-by-order book on integer ticks and lots.
#[pyclass(name = "Book")]
struct PyBook {
    inner: RBook,
}

#[pymethods]
impl PyBook {
    #[new]
    fn new() -> Self {
        PyBook { inner: RBook::new() }
    }

    fn add(&mut self, oid: u64, user: u32, side_: &str, tick: i64, lots: u64) -> PyResult<()> {
        let side = side(side_)?;
        if lots == 0 {
            return Err(PyValueError::new_err("order size is zero"));
        }
        if self.inner.contains(oid) {
            return Err(PyValueError::new_err(format!("order {oid} is already resting")));
        }
        self.inner.add(oid, user, side, tick, lots);
        Ok(())
    }

    fn cancel(&mut self, oid: u64) -> Option<u64> {
        self.inner.cancel(oid)
    }

    fn best_bid(&self) -> Option<(i64, u64)> {
        self.inner.best(Side::Bid)
    }

    fn best_ask(&self) -> Option<(i64, u64)> {
        self.inner.best(Side::Ask)
    }

    fn depth(&self, side_: &str, n: usize) -> PyResult<Vec<(i64, u64, u32)>> {
        Ok(self.inner.depth(side(side_)?, n))
    }

    fn queue_ahead(&self, oid: u64) -> Option<u64> {
        self.inner.queue_ahead(oid)
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }
}

#[pymodule]
fn hl_replay(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyBook>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
