from ultralytics import YOLO

def main():
    model = YOLO("yolo26_smartcook_v3.pt")

    model.train(
        data="train_data/dataset.yaml",
        epochs=100,
        imgsz=640,
        batch=4,          # 筆電 GPU 6~8GB 建議 4
        workers=2,
        fliplr=0.4,     # 左右翻轉
        flipud=0.1,     # 上下翻轉
        degrees=10,     # 旋轉
        scale=0.6,      # 縮放
        mosaic=0.5,     # mosaic augmentation
        mixup=0.2       # 混合圖片
    )
if __name__ == "__main__":
    main()