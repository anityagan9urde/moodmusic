"""Manual check: open the webcam, print quality + top blendshapes for 5 s."""
import time

from moodmusic.vision.camera import CameraSource
from moodmusic.vision.face import FaceTracker
from moodmusic.vision.quality import assess_quality

cam = CameraSource(0)
print("camera status:", cam.status)
tracker = FaceTracker()
start = time.monotonic()
last = 0.0
while time.monotonic() - start < 5:
    frame = cam.read()
    if frame is None:
        time.sleep(0.05)
        continue
    obs = tracker.process(frame, int((time.monotonic() - start) * 1000))
    if time.monotonic() - last > 0.5:
        last = time.monotonic()
        q = assess_quality(frame, obs)
        top = sorted(obs.blendshapes.items(), key=lambda kv: -kv[1])[:3]
        print(f"faces={obs.face_count} ok={q.ok} issue={q.issue} top={top}")
tracker.close()
cam.release()
