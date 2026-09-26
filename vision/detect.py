"""Vehicle detector (F2).

YOLOv8s / YOLO11s pretrained on COCO, fine-tuned on our ~400 labeled frames.
Classes: car, truck, bus, van. Input 640 (frames upscaled). Conf ~0.35.
"""

# TODO: Detector class wrapping ultralytics YOLO, batched across cameras
