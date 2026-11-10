"""Test camera connection and YOLO person detection directly without Redis, Docker, or DB.

Usage:
  python tools/test_camera_yolo.py
  python tools/test_camera_yolo.py --url "http://192.168.43.184:8080/video"
  python tools/test_camera_yolo.py --url 0   # to test with built-in laptop webcam
"""
import argparse
import os
import pathlib
import time
import cv2

# Patch pathlib.Path.exists to avoid Windows PermissionError on git check in ultralytics
_orig_exists = pathlib.Path.exists
def _safe_exists(self, *args, **kwargs):
    try:
        return _orig_exists(self, *args, **kwargs)
    except (PermissionError, OSError):
        return False
pathlib.Path.exists = _safe_exists

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


def get_default_url():
    # Try reading from twin3d/.env or .env
    for env_path in [".env", "twin3d/.env", "../.env"]:
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.strip().startswith("CAM01_URL="):
                        val = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
    return "http://192.168.43.184:8080/video"


def find_model(model_arg: str):
    if os.path.exists(model_arg):
        return model_arg
    candidates = [
        "yolo26n.pt",
        "../yolo26n.pt",
        "../../yolo26n.pt",
        "yolov8n.pt"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return model_arg


def main():
    parser = argparse.ArgumentParser(description="Test Camera Stream & YOLO Person Detection")
    parser.add_argument("--url", default=None, help="RTSP / HTTP stream URL or 0 for local webcam")
    parser.add_argument("--model", default="yolo26n.pt", help="Path to YOLO weights (.pt)")
    parser.add_argument("--conf", type=float, default=0.35, help="Confidence threshold")
    args = parser.parse_args()

    stream_url = args.url if args.url is not None else get_default_url()
    # Check if user specified webcam index (e.g. "0")
    if stream_url.isdigit():
        stream_source = int(stream_url)
    else:
        stream_source = stream_url

    model_path = find_model(args.model)
    print("=" * 60)
    print(" Twin3D: Camera & YOLO Standalone Test")
    print("=" * 60)
    print(f"Loading YOLO Model : {model_path}")
    from ultralytics import YOLO
    model = YOLO(model_path)
    print("YOLO Model loaded successfully!")

    print(f"\nConnecting to Stream: {stream_source}")
    print("Press 'q' or 'ESC' in the video window to quit.\n")

    cap = cv2.VideoCapture(stream_source)
    if not cap.isOpened():
        print(f"\n[ERROR] Could not open video source: {stream_source}")
        print("Tips for IP Webcam on Android:")
        print(" - Verify phone and PC are on the same WiFi network.")
        print(" - Try the MJPEG endpoint: http://<phone-ip>:8080/video")
        print(" - Try the RTSP endpoint : rtsp://<phone-ip>:8080/h264_stream")
        print(" - To test your PC webcam, run: python tools/test_camera_yolo.py --url 0")
        return

    fps_count, prev_time = 0, time.time()
    current_fps = 0.0

    cv2.namedWindow("Twin3D - Camera & YOLO Test", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Twin3D - Camera & YOLO Test", 960, 540)

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                print("Waiting for frames from stream...")
                time.sleep(0.1)
                continue

            fps_count += 1
            now = time.time()
            if now - prev_time >= 1.0:
                current_fps = fps_count / (now - prev_time)
                fps_count = 0
                prev_time = now

            # Run YOLO person detection (class 0 = person)
            results = model.predict(frame, classes=[0], conf=args.conf, verbose=False)[0]
            boxes = results.boxes

            person_count = 0
            if boxes is not None:
                for box in boxes:
                    person_count += 1
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    conf = float(box.conf[0])

                    # Bounding box
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 120), 2)
                    
                    # Foot point (used for 3D floor mapping)
                    foot_x = (x1 + x2) // 2
                    foot_y = y2
                    cv2.circle(frame, (foot_x, foot_y), 5, (0, 0, 255), -1)

                    # Label
                    label = f"Person {conf:.2f}"
                    t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                    cv2.rectangle(frame, (x1, y1 - 20), (x1 + t_size[0] + 6, y1), (0, 255, 120), -1)
                    cv2.putText(frame, label, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

            # Overlay HUD
            hud_bg = frame.copy()
            cv2.rectangle(hud_bg, (10, 10), (320, 85), (20, 20, 20), -1)
            cv2.addWeighted(hud_bg, 0.6, frame, 0.4, 0, frame)

            cv2.putText(frame, f"FPS: {current_fps:.1f}", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(frame, f"People Detected: {person_count}", (20, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            cv2.imshow("Twin3D - Camera & YOLO Test", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:  # 'q' or ESC
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("\nTest finished. Stream released.")


if __name__ == "__main__":
    main()
