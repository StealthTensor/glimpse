# Face Engine

The engine is backend-independent.

Pipeline: 1. Capture frame. 2. Detect face. 3. Reject frames with
unsuitable quality. 4. Align/crop face. 5. Run liveness. 6. Generate
embedding. 7. Compare against enrolled templates. 8. Aggregate multiple
frames. 9. Return authenticated/rejected/indeterminate.

Initial implementation may use Howdy's existing engine. A future native
ONNX backend should be supported without changing PAM or policy layers.

Similarity thresholds must be calibrated on the target camera and
enrollment data; never copy an arbitrary threshold into production.
