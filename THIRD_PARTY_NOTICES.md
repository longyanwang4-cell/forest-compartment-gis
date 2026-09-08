# Third-party notices

This repository's original code is provided under the MIT License in [LICENSE](LICENSE).

The project does not bundle the third-party runtimes below. They are external dependencies and remain under their own terms:

| Component | How this project uses it | License status |
| --- | --- | --- |
| ArcGIS Pro / ArcPy | Optional proprietary backend for geodatabase construction and validation | Esri commercial software; users must provide a valid license. Verify current Esri terms before redistribution. |
| NumPy, SciPy, pandas | Numerical and tabular processing | Verify current upstream license before redistribution |
| Rasterio, Fiona, GeoPandas, Shapely, PyProj | Raster/vector metadata and geometry operations | Verify current upstream license before redistribution |
| scikit-image, scikit-learn | Optional candidate segmentation dependencies | Verify current upstream license before redistribution |

These packages are referenced by `requirements-segmentation.txt` or imports in the source. Their names and code are not relicensed by this repository's MIT License. Consult the authoritative upstream project notices and installed package metadata for the exact version-specific terms. This file is an informational notice, not legal advice.
