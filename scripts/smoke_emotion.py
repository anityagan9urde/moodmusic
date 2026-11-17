"""Manual smoke test: load the real emotion model and run it on a blank image."""
import numpy as np

from moodmusic.vision.emotion import HSEmotionModel

r = HSEmotionModel().predict(np.zeros((224, 224, 3), np.uint8))
print(r)
