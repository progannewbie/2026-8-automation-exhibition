import os
import json
# LabelMe label -> YOLO class id
classes = {
    "CUCUMBER": 0,
    "CORN": 1,
    "CARROT": 2
}
json_folder = "label"
output_folder = "label_txt"
os.makedirs(output_folder, exist_ok=True)
def convert_json(json_path, output_path):

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    img_w = data["imageWidth"]
    img_h = data["imageHeight"]
    yolo_lines = []
    for shape in data["shapes"]:
        label = shape["label"]
        if label not in classes:
            print(
                f"Warning: unknown label {label}"
            )
            continue
        class_id = classes[label]
        if shape["shape_type"] != "oriented_rectangle":
            print(
                f"Skip {label}: not oriented_rectangle"
            )
            continue
        points = shape["points"]
        values = [str(class_id)]
        for x, y in points:
            # normalize
            x = x / img_w
            y = y / img_h
            values.append(
                f"{x:.6f}"
            )

            values.append(
                f"{y:.6f}"
            )
        yolo_lines.append(
            " ".join(values)
        )
    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(
            "\n".join(yolo_lines)
        )
# batch convert
for filename in os.listdir(json_folder):
    if filename.endswith(".json"):
        json_path = os.path.join(
            json_folder,
            filename
        )
        txt_name = filename.replace(
            ".json",
            ".txt"
        )
        output_path = os.path.join(
            output_folder,
            txt_name
        )
        convert_json(
            json_path,
            output_path
        )
        print(
            f"Converted: {filename}"
        )
print("Done!")