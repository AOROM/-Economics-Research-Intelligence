# Identification and method taxonomy

Use labels only when the paper itself names or clearly describes the method:

- DID: traditional, staggered, event study, triple difference.
- IV: policy, geographic, shift-share/Bartik.
- RDD: sharp, fuzzy, spatial.
- Other designs: natural experiment, RCT, panel fixed effects, synthetic control, matching, structural estimation, network analysis, text-as-data, machine learning, descriptive/decomposition.

The executable extractor recognizes a conservative subset of these labels from title and abstract. It does not decide whether the design is valid. In particular, an English sentence containing the ordinary verb “did” must not trigger the DID label. Record treatment, control, timing, and identifying assumption separately when accessible paper text supports them.
