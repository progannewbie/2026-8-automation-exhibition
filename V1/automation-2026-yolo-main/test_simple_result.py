from ultralytics import YOLO
import matplotlib.pyplot as plt


MODEL_PATH = "yolo26_smartcook_v4.pt"
IMAGE_PATH = r"train_data\images\val\new3_capture_024.jpg"


model = YOLO(MODEL_PATH)

results = model(IMAGE_PATH)


for result in results:

    img = result.plot()

    # OpenCV BGR -> RGB
    img = img[:, :, ::-1]

    plt.figure(figsize=(10,8))
    plt.imshow(img)
    plt.axis("off")
    plt.show()