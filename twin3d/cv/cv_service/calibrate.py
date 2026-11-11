"""Click ground points in a camera frame, pair them with measured floor coordinates (metres), save homography.

  python -m cv_service.calibrate --image frame.jpg --world "2,2;10,2;10,8;2,8" --out calib/cam01.json
Click the pixels in the SAME ORDER as the world points, then press Enter.  Rejects error > 0.30 m.
"""
import argparse, json, os
import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--world", required=True, help='"x,y;x,y;..." metres, min 4 points')
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    world = np.array([[float(v) for v in p.split(",")] for p in a.world.split(";")], dtype=np.float32)
    img = cv2.imread(a.image)
    if img is None:
        raise SystemExit(f"Error: Could not load calibration image from '{a.image}'. File not found or invalid format.")
    pts: list[list[int]] = []

    def on_mouse(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN and len(pts) < len(world):
            pts.append([x, y])
            cv2.circle(img, (x, y), 5, (0, 0, 255), -1)
            cv2.putText(img, str(len(pts)), (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    cv2.namedWindow("calibrate")
    cv2.setMouseCallback("calibrate", on_mouse)
    while True:
        cv2.imshow("calibrate", img)
        if cv2.waitKey(30) in (13, 10) and len(pts) == len(world):
            break
    cv2.destroyAllWindows()
    px = np.array(pts, dtype=np.float32)
    H, _ = cv2.findHomography(px, world, cv2.RANSAC, 3.0)
    back = cv2.perspectiveTransform(px.reshape(1, -1, 2), H)[0]
    err = float(np.linalg.norm(back - world, axis=1).mean())
    print(f"mean reprojection error: {err*100:.1f} cm")
    if err > 0.30:
        raise SystemExit("error above 30 cm: re-measure the floor points and try again")
    out_dir = os.path.dirname(a.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    json.dump({"H": H.tolist(), "pixel_points": px.tolist(), "world_points": world.tolist(),
               "error_m": err, "image_size": [img.shape[1], img.shape[0]]}, open(a.out, "w"), indent=2)
    print("saved", a.out)


if __name__ == "__main__":
    main()
