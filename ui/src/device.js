export function normalizeModelIdentifier(value) {
  return String(value ?? "")
    .split("")
    .filter((char) => /[a-z0-9]/i.test(char))
    .join("")
    .toLowerCase();
}

export function slugify(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function parseList(value) {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function buildCreateDevicePayload(fields) {
  const brand = String(fields.brand ?? "").trim();
  const model = String(fields.model ?? "").trim();
  const deviceType = String(fields.device_type ?? "").trim().toLowerCase();
  const room = String(fields.room ?? "").trim();
  const aliases = parseList(fields.aliases);
  const normalizedModel = normalizeModelIdentifier(model);
  const assetId =
    String(fields.asset_id ?? "").trim() ||
    [deviceType, brand, model].map(slugify).filter(Boolean).join("-");

  return {
    asset_id: assetId,
    device_type: deviceType,
    brand,
    model,
    normalized_model: normalizedModel,
    aliases,
    room: room || null
  };
}
