// Selectable transaction locations, each carrying an IANA timezone so the form
// can show the location's live local time and its IST equivalent.

export interface GeoLocation {
  label: string; // stored verbatim as transaction.location
  tz: string; // IANA timezone id
}

export const LOCATIONS: GeoLocation[] = [
  { label: "Mumbai, IN", tz: "Asia/Kolkata" },
  { label: "Delhi, IN", tz: "Asia/Kolkata" },
  { label: "New York, US", tz: "America/New_York" },
  { label: "London, GB", tz: "Europe/London" },
  { label: "Paris, FR", tz: "Europe/Paris" },
  { label: "Moscow, RU", tz: "Europe/Moscow" },
  { label: "Dubai, AE", tz: "Asia/Dubai" },
  { label: "Singapore, SG", tz: "Asia/Singapore" },
  { label: "Tokyo, JP", tz: "Asia/Tokyo" },
  { label: "Sydney, AU", tz: "Australia/Sydney" },
];

export const IST_TZ = "Asia/Kolkata";

export function tzForLocation(label: string | null | undefined): string {
  return LOCATIONS.find((l) => l.label === label)?.tz ?? IST_TZ;
}
