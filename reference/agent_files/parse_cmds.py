import pandas as pd
df = pd.read_excel('docs/ref_files/ESCVP21 command guide for business projector Rev.G.xlsx', sheet_name=None)
cmds = set()
for name, sheet in df.items():
    if "Sheet" in name or "list" in name or "How to" in name: continue
    for col in sheet.columns:
        for val in sheet[col].dropna():
            val = str(val).strip()
            if len(val) > 2 and val.isupper() and " " not in val and not any(c.isdigit() for c in val):
                cmds.add(val.split()[0])
print(sorted(list(cmds))[:50])
