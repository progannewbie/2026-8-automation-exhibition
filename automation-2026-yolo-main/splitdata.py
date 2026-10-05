import os
import shutil
import random
from pathlib import Path


# 原始資料
IMAGE_DIR = Path("images")
LABEL_DIR = Path("label_txt")

# 輸出資料
OUTPUT_DIR = Path("train_data")

TRAIN_RATIO = 0.8   # 80% train


# 建立資料夾
folders = [
    OUTPUT_DIR / "images" / "train",
    OUTPUT_DIR / "images" / "val",
    OUTPUT_DIR / "labels" / "train",
    OUTPUT_DIR / "labels" / "val",
]

for folder in folders:
    folder.mkdir(parents=True, exist_ok=True)


# 支援圖片格式
IMAGE_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
]


# 取得所有圖片
images = []

for ext in IMAGE_EXTENSIONS:
    images.extend(IMAGE_DIR.glob(f"new2_*{ext}"))


print(f"找到圖片數量: {len(images)}")


# 隨機打亂
random.shuffle(images)


# 分割
train_count = int(len(images) * TRAIN_RATIO)

train_images = images[:train_count]
val_images = images[train_count:]


def copy_data(image_files, split):

    for img_path in image_files:

        # 圖片名稱
        name = img_path.stem

        # 對應label
        label_path = LABEL_DIR / f"{name}.txt"


        # 檢查標註是否存在
        if not label_path.exists():
            print(f"⚠ 找不到標註: {label_path}")
            continue


        # 目的地
        dst_image = OUTPUT_DIR / "images" / split / img_path.name
        dst_label = OUTPUT_DIR / "labels" / split / label_path.name


        # 複製
        shutil.copy(img_path, dst_image)
        shutil.copy(label_path, dst_label)


        print(f"{split}: {img_path.name}")


# 執行
copy_data(train_images, "train")
copy_data(val_images, "val")


print("\n完成!")
print(f"Train: {len(train_images)}")
print(f"Val: {len(val_images)}")