export function parseRoles(roleValue) {
  if (Array.isArray(roleValue)) {
    return [...new Set(roleValue.flatMap(parseRoles))];
  }
  if (typeof roleValue !== "string") {
    return [];
  }
  return [...new Set(
    roleValue
      .split(",")
      .map((role) => role.trim().toLowerCase())
      .filter(Boolean)
  )];
}

export function hasRole(roleValue, role) {
  const target = String(role || "").trim().toLowerCase();
  return !!target && parseRoles(roleValue).includes(target);
}

export function hasAnyRole(roleValue, roles) {
  const parsed = new Set(parseRoles(roleValue));
  return (roles || []).some((role) => parsed.has(String(role || "").trim().toLowerCase()));
}
