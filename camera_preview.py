"""Live webcam preview for positioning the camera. Close the window or press Q to stop.

    python camera_preview.py 1
"""
import sys

import cv2

cap = cv2.VideoCapture(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
cv2.namedWindow("camera", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("camera", cv2.WND_PROP_TOPMOST, 1)
while True:
    ok, frame = cap.read()
    if ok:
        cv2.imshow("camera", frame)
    if cv2.waitKey(30) & 0xFF == ord("q") or cv2.getWindowProperty("camera", cv2.WND_PROP_VISIBLE) < 1:
        break
cv2.imwrite("plots/camera_position.jpg", frame)  # last frame, so the placement can be checked
cap.release()
cv2.destroyAllWindows()
