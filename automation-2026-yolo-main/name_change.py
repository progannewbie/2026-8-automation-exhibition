from pathlib import Path

folder = Path(r"captures")

for file in folder.iterdir():
    if file.is_file() and file.suffix.lower() == ".jpg":
        if not file.name.startswith("new2_"):
            new_name = "new2_" + file.name
            file.rename(file.with_name(new_name))
            print(f"{file.name} -> {new_name}")

print("完成！")