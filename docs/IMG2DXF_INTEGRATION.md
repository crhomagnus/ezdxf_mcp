# Image-to-DXF and Spatial Recognition

## Purpose

The image extension adds two independent capabilities:

1. convert PNG/JPG pixels into native DXF geometry and text;
2. inventory components in generated or generic DXF files and describe their
   identity, WCS position, dimensions, and spatial relationships.

## Conversion pipeline

`dxf_image_to_dxf`:

1. resolves input and output paths inside `EZDXF_MCP_WORKSPACE`;
2. validates extension, file size, pixel count, and overwrite policy;
3. decodes the image and converts it to grayscale;
4. applies Otsu, fixed, adaptive, or Canny thresholding;
5. reads words through Tesseract TSV and applies confidence filters;
6. rejects implausibly large OCR boxes;
7. masks accepted words to avoid duplicating their glyphs as contours;
8. extracts the complete contour hierarchy, including holes;
9. detects circles and fits other contours with the selected curve mode;
10. transforms image pixels into Cartesian DXF coordinates;
11. creates native `TEXT`, geometry layers, and `IMG2DXF` XDATA;
12. audits and saves the DXF, then returns a resident `doc_id`.

Generated layers:

- `IMG_OUTLINE`: external contours;
- `IMG_HOLE`: internal contours and holes;
- `IMG_ANALYTIC`: recognized analytical primitives;
- `IMG_TEXT`: OCR words;
- `IMG_RASTER`: optional external raster reference.

## Scale and coordinate system

Exactly one scale source may be supplied:

- `width_mm`: physical width divided by pixel width;
- `dpi`: `25.4 / dpi`;
- `mm_per_pixel`: direct scale;
- none: fallback to 1 unit per pixel with a warning.

Images start at the upper-left and increase downward. DXF uses a lower-left
origin and increases upward. For a pixel box `(left, top, width, height)`,
image height `H`, and scale `s`:

```text
x_min = left * s
x_max = (left + width) * s
y_min = (H - top - height) * s
y_max = (H - top) * s
```

The source pixel box is stored in XDATA, making reconstruction deterministic
for components created by this pipeline.

## Component recognition

`dxf_recognize_components` groups entities belonging to the same vectorized
component and inventories standalone entities in generic drawings. A result
can include:

- semantic type, DXF types, handles, layer, and entity count;
- WCS bounds, center, dimensions, and declared precision;
- text, radius, angles, vertices, block data, or image references;
- pairwise containment, overlap, touch, direction, and distance;
- nearest-component information.

Topological relationships are computed over WCS bounding boxes. They do not
claim exact Boolean intersection of arbitrary curves.

Precision is explicit:

- line, point, and circle geometry is analytical;
- `IMAGE` uses its exact WCS boundary;
- curve bounds use controlled flattening;
- generic text bounds depend on available font metrics;
- generated components can preserve exact transformed source pixel boxes.

## OCR inside a DXF IMAGE entity

DXF `IMAGE` entities reference an external raster file; they do not embed its
bytes. When the file exists inside the workspace and image OCR is enabled, the
recognizer:

1. reads words through Tesseract;
2. creates virtual `text_in_image` components;
3. associates each word with its parent image;
4. maps the four pixel-box corners into WCS with `insert`, `u_pixel`, and
   `v_pixel`.

Rotation, scale, and orientation of the referenced image are preserved.

## Limitations

- Photographic noise may require threshold tuning.
- OCR depends on installed language packs and source quality.
- Unlabeled symbols cannot always be assigned a real-world meaning.
- Circle detection is tolerance-based.
- Generic text metrics may vary with font substitution.
- Vector fitting is an approximation of raster pixels, not recovery of an
  unknown original vector source.
- Use line mode when strict screen-envelope preservation matters more than
  curve compactness.
