import pandas as pd
df = pd.read_excel('docs/ref_files/ESCVP21 command guide for business projector Rev.G.xlsx', sheet_name='Basic')
for i, row in df.iterrows():
    cmd = str(row.iloc[0]).strip()
    param = str(row.iloc[1]).strip()
    func = str(row.iloc[2]).strip()
    if len(cmd) > 1 and cmd != 'nan' and not cmd.startswith('('):
        print(f"{cmd.ljust(15)} {param.ljust(20)} {func}")
