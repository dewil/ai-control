# JPEG Samsung SEF trailer compatibility

Proposal, 13.10.2026. Parent: CONTROL-WEB-ATTACHMENTS. Fix the r29 finish refusal for an otherwise valid JPEG followed by Samsung SEF metadata. No dependency, decoder, reencoding, native fallback or permission change.

Observed safe structure only: 591128 total bytes, primary JPEG EOI at590961, trailer167bytes; SEFH begins123bytes after EOI, version107, two entries; directory36bytes and terminal SEFT. Metadata blocks38+85bytes exactly precede the directory. No private image or metadata payload enters fixtures/artifacts/cloud. The current EOI-equals-file-size condition rejects it with unsupported. No missing image dependency is involved.

INV-WATT-JPEG-SEF: after the existing valid JPEG SOF/SOS/EOI and resource checks, accept a metadata-only SEF trailer when all following bounds hold:

- Total trailer <=65536bytes; fixed EOF footer is uint32LE directory length + SEFT.
- Footer resolves a SEFH directory entirely after primary EOI. Version101 or107; entry count1..256; directory length exactly12+12*count.
- Each12byte directory record is reserved uint16LEzero, type uint16LE, backward offset uint32LE relative to SEFH, size uint32LE. Size>=8; record points entirely into the post-EOI/pre-directory region. The pointed block begins with the same reserved/type bytes and uint32LE name length; name length <= size-8. Names and data remain opaque and are neither decoded nor executed.
- Sorted block ranges are disjoint and cover exactly EOI..SEFH. No second JPEG SOI occurs in the trailer. Arbitrary tails, truncated footer/header/table, offset/length overflow, overlapping records, extra bytes and unsupported versions fail unsupported.
- Preserve every original byte, original size and SHA256 through stage finish/seal/native projection. Accepted mode=image. Existing image dimensions/pixel limit, encoded payload limit and malformed JPEG/PNG rejection remain unchanged. No strip/reencode and no fallback to generic file.

This intentionally supports bounded metadata-only SEF, not Motion Photo, extra embedded images, arbitrary concatenation or a general multimedia container. Existing capability/native proof gates remain. Shipping this parser fix uses unchanged native projection checks and installed JPEG validation; device/native consumption acceptance is a separate user test after deploy. Do not launch paid inference for this fix or equate installed validation with successful consumption.

Primary format source: [ExifTool Samsung ProcessSamsung](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/Samsung.pm), directory/footer backward offset format. ExifTool tolerates some damaged Gallery tails; this proposal requires complete bounded structure. Synthetic tests construct metadata, never copy private bytes. The diagnostic author inspected the old parser: tests are independently specified regressions, not a claim of clean-context SDD blindness. Usage receipt unknown; parent writes ledger.

Composer failure contract: an explicit finish refusal `unsupported` shows «Формат изображения не поддерживается или файл повреждён.», retains the chip/draft, keeps send disabled, and never retries automatically. This does not alter HTTP status design.
