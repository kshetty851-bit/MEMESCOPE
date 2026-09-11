"""An `NseArchive` stand-in that never opens a socket, plus a bhavcopy builder."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import Any

HEADER = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,"
          "XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,"
          "LwPric,ClsPric,LastPr,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
          "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,"
          "Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4")


def row(symbol: str, when: date, *, o=100.0, h=105.0, low=99.0, c=104.0,
        volume=10_000, turnover=1_040_000.0, series="EQ", instrument="STK",
        name: str | None = None) -> str:
    """One bhavcopy line in the real column order."""
    f = [""] * 34
    f[0] = f[1] = when.isoformat()
    f[2], f[3], f[4] = "CM", "NSE", instrument
    f[5], f[6] = "1", f"INE{symbol[:6]:0<6}01"
    f[7], f[8] = symbol, series
    f[13] = name or symbol
    f[14], f[15], f[16], f[17] = f"{o}", f"{h}", f"{low}", f"{c}"
    f[18] = f"{c}"
    f[24], f[25] = str(volume), f"{turnover}"
    return ",".join(f)


def csv_for(when: date, rows: list[str]) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


def zip_for(when: date, rows: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"BhavCopy_{when:%Y%m%d}.csv", csv_for(when, rows))
    return buf.getvalue()


INDEX_CSV = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
    "Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.)\n"
    "Nifty 50,{d},23300.00,23400.10,23250.00,{c},56.25,0.24,1,2\n")


class FakeArchive:
    """Records every call. `days` maps a date to its rows; a date that is
    absent raises `NotPublished`, exactly as a holiday does."""

    def __init__(self, days: dict[date, list[str]] | None = None,
                 *, index: dict[date, float] | None = None,
                 fail: set[date] | None = None) -> None:
        self.days = days or {}
        self.index = index or {}
        self.fail = fail or set()
        self.requests = 0
        self.calls: list[Any] = []

    async def bhavcopy(self, when: date) -> bytes:
        from app.labs.nse_breakout.sources import NotPublished

        self.requests += 1
        self.calls.append(("bhavcopy", when))
        if when in self.fail:
            raise RuntimeError(f"boom for {when}")
        if when not in self.days:
            raise NotPublished(str(when))
        return zip_for(when, self.days[when])

    async def index_closes(self, when: date) -> str:
        from app.labs.nse_breakout.sources import NotPublished

        self.requests += 1
        self.calls.append(("index", when))
        if when not in self.index:
            raise NotPublished(str(when))
        return INDEX_CSV.format(d=when.strftime("%d-%m-%Y"), c=self.index[when])
