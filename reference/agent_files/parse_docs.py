import pandas as pd

df = pd.read_excel('docs/ref_files/ESCVP21 command guide for business projector Rev.G.xlsx', sheet_name=None)
with open('docs/ref_files/xlsx_dump.txt', 'w') as f:
    for name, sheet in df.items():
        f.write(f"\n--- Sheet: {name} ---\n")
        f.write(sheet.to_csv())
print("XLSX parsed.")
