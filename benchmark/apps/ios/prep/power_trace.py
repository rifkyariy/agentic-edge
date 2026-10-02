"""Turn iPhone power data into power.json for the GemmaBench app. Two sources:

    python3 prep/power_trace.py --powerlog <sysdiagnose.tar.gz | .PLSQL>   # any Xcode, or none
    python3 prep/power_trace.py <trace>            # Power Profiler trace, needs Xcode 26 xctrace
    python3 prep/power_trace.py <file> --toc       # list tables/columns (debug either source)
    python3 prep/power_trace.py --demo             # self-check of both parsers

PowerLog (kind "watts"): the battery fuel gauge's own voltage x current and temperature, from
the powerlog database every sysdiagnose carries. Real watts at the battery, sampled sparsely
(tens of seconds) — good for whole-run energy, too coarse per question. Undocumented format.

<trace> is a .trace, or the file from the phone's Performance Trace (Settings >
Developer > Performance Trace) — if xctrace won't read that directly, open it in
Instruments and File > Save As a .trace. Needs Xcode 26's xctrace.

Output: {"source", "kind", "trace_start", "series": [{"name", "t": [epoch s], "v": [...]}]}.
kind "impact": Power Profiler's relative score, not watts. kind "watts": PowerLog battery power.
Stdlib only.
"""
import json, os, re, sqlite3, subprocess, sys, tarfile, tempfile, xml.etree.ElementTree as ET
from datetime import datetime

POWER = re.compile(r"power|impact|energy", re.I)


def xctrace(trace, *args):
    return subprocess.run(["xcrun", "xctrace", "export", "--input", trace, *args],
                          check=True, capture_output=True, text=True).stdout


def trace_start(toc):
    s = toc.find(".//run/info/summary/start-date").text.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def power_tables(toc):
    # ponytail: Apple doesn't document Power Profiler's schema names, so match on the
    # name; `--toc` shows what a real trace calls them if this ever picks the wrong ones.
    return sorted({t.get("schema") for t in toc.iter("table") if POWER.search(t.get("schema") or "")})


def parse_table(xml, start):
    """xctrace table XML -> {column: (t[], v[])}. Handles id/ref de-duplication: a value
    appears once with id="N" and later rows point at it with ref="N"."""
    root = ET.fromstring(xml)
    cols = [c.findtext("mnemonic") for c in root.iter("col")]
    seen, out = {}, {}
    for row in root.iter("row"):
        cells = []
        for el in row:
            if "ref" in el.attrib:
                el = seen.get(el.get("ref"), el)
            elif "id" in el.attrib:
                seen[el.get("id")] = el
            cells.append(el)
        t = next((float(c.text) for c in cells if c.tag.endswith("time") and "duration" not in c.tag and c.text), None)
        if t is None:
            continue
        for name, c in zip(cols, cells):
            if c.tag.endswith("time") or c.text is None:
                continue
            try:
                v = float(c.text)
            except ValueError:
                continue  # labels, process names, enums
            ts, vs = out.setdefault(name, ([], []))
            ts.append(round(start + t / 1e9, 3))  # trace times are ns since trace start
            vs.append(v)
    return out


def main(trace, toc_only=False):
    toc = ET.fromstring(xctrace(trace, "--toc"))
    if toc_only:
        for t in toc.iter("table"):
            print(t.get("schema"), {k: v for k, v in t.attrib.items() if k != "schema"})
        return
    start, series = trace_start(toc), []
    tables = power_tables(toc)
    if not tables:
        raise SystemExit("no power tables in this trace — run with --toc and check it was recorded with Power Profiler")
    for schema in tables:
        rows = parse_table(xctrace(trace, "--xpath", f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]'), start)
        for col, (t, v) in rows.items():
            if len(set(v)) > 1:  # constant columns (ids, flags) aren't a signal
                series.append({"name": f"{schema}/{col}", "t": t, "v": v})
    out = trace.rstrip("/") + ".power.json"
    json.dump({"source": trace, "kind": "impact", "trace_start": start, "series": series}, open(out, "w"))
    print("wrote", out, [s["name"] for s in series])


# MARK: PowerLog (sysdiagnose)

def plsql_path(path, tmp):
    """The powerlog database: the file itself, or the newest *.PLSQL inside a sysdiagnose archive
    (extracted with its -wal/-shm so sqlite sees the latest rows)."""
    if not tarfile.is_tarfile(path):
        return path
    with tarfile.open(path) as tf:
        dbs = [m for m in tf.getmembers() if re.search(r"powerlog.*\.PLSQL$", m.name, re.I) and m.isfile()]
        if not dbs:
            raise SystemExit("no powerlog *.PLSQL in this archive")
        db = max(dbs, key=lambda m: (m.mtime, m.size))
        for m in tf.getmembers():
            if m.name.startswith(db.name) and m.isfile():  # the db plus -wal / -shm
                m.name = os.path.basename(m.name)
                tf.extract(m, tmp)
        return os.path.join(tmp, os.path.basename(db.name))


def battery_table(con):
    """First table with voltage + instant current. ponytail: matched by column name because
    Apple renames PowerLog tables between iOS versions; `--toc` shows the real ones."""
    names = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    names.sort(key=lambda n: ("BatteryUI" in n, "Battery" not in n))  # prefer the raw battery agent table
    for n in names:
        cols = [r[1] for r in con.execute(f'pragma table_info("{n}")')]
        if {"Voltage", "InstantAmperage", "timestamp"} <= set(cols):
            return n, cols
    raise SystemExit("no battery table with Voltage/InstantAmperage — run with --toc")


def powerlog(path, toc_only=False):
    with tempfile.TemporaryDirectory() as tmp:
        con = sqlite3.connect(f"file:{plsql_path(path, tmp)}?mode=ro", uri=True)
        if toc_only:
            for (n,) in con.execute("select name from sqlite_master where type='table' and name like '%Battery%'"):
                print(n, [r[1] for r in con.execute(f'pragma table_info("{n}")')])
            return
        table, cols = battery_table(con)
        temp = "Temperature" if "Temperature" in cols else "NULL"
        rows = con.execute(f'select timestamp, Voltage, InstantAmperage, {temp} from "{table}" '
                           "where Voltage > 0 order by timestamp").fetchall()
    series = to_series(rows)
    out = path + ".power.json"
    json.dump({"source": f"{os.path.basename(path)}:{table}", "kind": "watts",
               "trace_start": series[0]["t"][0] if series and series[0]["t"] else 0, "series": series}, open(out, "w"))
    print("wrote", out, {s["name"]: len(s["t"]) for s in series})


def to_series(rows):
    """(timestamp, mV, mA, temp) rows -> power_w / voltage_v / current_a / temp_c series.
    Discharge is reported negative; flip so power while running on battery is positive."""
    if not rows:
        return []
    ts = [r[0] + (978307200 if r[0] < 1e9 else 0) for r in rows]  # tolerate Mac absolute time
    sign = -1 if sorted(r[2] for r in rows)[len(rows) // 2] < 0 else 1
    v = [r[1] / 1000 for r in rows]
    a = [sign * r[2] / 1000 for r in rows]
    out = [{"name": "battery/power_w", "t": ts, "v": [round(x * y, 3) for x, y in zip(v, a)]},
           {"name": "battery/voltage_v", "t": ts, "v": v},
           {"name": "battery/current_a", "t": ts, "v": a}]
    temps = [(t, r[3]) for t, r in zip(ts, rows) if r[3] is not None]
    if temps:
        scale = 100 if sorted(x for _, x in temps)[len(temps) // 2] > 200 else 1  # centi-degrees on most builds
        out.append({"name": "battery/temp_c", "t": [t for t, _ in temps], "v": [x / scale for _, x in temps]})
    return out


def demo():
    xml = """<trace-query-result><node><schema name="power-impact">
      <col><mnemonic>start</mnemonic></col><col><mnemonic>cpu-impact</mnemonic></col><col><mnemonic>process</mnemonic></col>
    </schema>
    <row><start-time id="1" fmt="00:00.000">0</start-time><double id="2">1.5</double><process id="3" fmt="GemmaBench">x</process></row>
    <row><start-time id="4">1000000000</start-time><double ref="2"/><process ref="3"/></row>
    <row><start-time id="5">2000000000</start-time><double id="6">21</double><process ref="3"/></row>
    </node></trace-query-result>"""
    got = parse_table(xml, 100.0)
    assert got == {"cpu-impact": ([100.0, 101.0, 102.0], [1.5, 1.5, 21.0])}, got
    toc = ET.fromstring('<trace-toc><run number="1"><info><summary><start-date>2026-09-26T10:00:00.000+08:00</start-date>'
                        '</summary></info><data><table schema="power-impact"/><table schema="time-profile"/></data></run></trace-toc>')
    assert power_tables(toc) == ["power-impact"]
    assert trace_start(toc) == datetime.fromisoformat("2026-09-26T10:00:00+08:00").timestamp()

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "powerlog_demo.PLSQL")
        con = sqlite3.connect(db)
        con.execute("create table PLBatteryAgent_EventBackward_BatteryUI (timestamp, Level)")
        con.execute("create table PLBatteryAgent_EventBackward_Battery (timestamp, Voltage, InstantAmperage, Temperature)")
        con.executemany("insert into PLBatteryAgent_EventBackward_Battery values (?,?,?,?)",
                        [(1790000000, 4000, -1000, 3050), (1790000030, 3990, -1500, 3120), (1790000060, 0, 0, 0)])
        con.commit(); con.close()
        tar = os.path.join(tmp, "sysdiagnose_demo.tar.gz")
        with tarfile.open(tar, "w:gz") as tf:
            tf.add(db, arcname="sysdiagnose_demo/logs/powerlogs/powerlog_demo.PLSQL")
        powerlog(tar)
        got = {s["name"]: s["v"] for s in json.load(open(tar + ".power.json"))["series"]}
    assert got["battery/power_w"] == [4.0, 5.985], got  # 4.0 V x 1.0 A, 3.99 V x 1.5 A; the 0 V row dropped
    assert got["battery/temp_c"] == [30.5, 31.2], got
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--demo"]:
        demo()
    elif sys.argv[1:2] == ["--powerlog"] and len(sys.argv) > 2:
        powerlog(sys.argv[2], "--toc" in sys.argv)
    elif len(sys.argv) > 1:
        main(sys.argv[1], "--toc" in sys.argv)
    else:
        raise SystemExit(__doc__)
