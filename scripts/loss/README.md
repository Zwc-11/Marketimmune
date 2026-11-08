# Live paper losses, every run (2026-11-08)

`report_all.sh` runs `paper_report` on each PC live run (pulled from `G:\\Crypto Data\\paper`, staged under `/mnt/user-data/uploads/Crypto Data/paper`); `curve.py` builds one table of every live fill with its markout at 0.2 s to 300 s and the move in the second before it; `final.py` writes the CSVs in `eval/paper/loss/`.
