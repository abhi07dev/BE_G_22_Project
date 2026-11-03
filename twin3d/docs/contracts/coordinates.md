# Floor coordinate system (owner: Member 3)

- Origin: bottom-left corner of the floor plan. X to the right, Y up the plan. Units: metres.
- Three.js mapping: world (x, y) becomes scene (x, 0, -y).
- Floor size and zones live in `backend/app/data/floor_f1.json` until the DB-backed admin pages exist.
- Calibration: measure 4-8 floor points with a tape, click them in the camera frame with `cv_service/calibrate.py`. Reject above 30 cm error.
