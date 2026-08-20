/**
 * All-India Locations & Multi-City Registry
 * Covers all states, union territories, major metropolitan areas, and smart cities.
 */

export interface IndiaLocation {
  id: string;
  name: string;
  state: string;
  region: string;
  coordinates: [number, number]; // [lng, lat]
  zoom: number;
  cad_zone: string;
}

export const INDIA_LOCATIONS: IndiaLocation[] = [
  {
    id: "all_india",
    name: "All-India Overview",
    state: "National",
    region: "National Command",
    coordinates: [78.9629, 20.5937],
    zoom: 4.8,
    cad_zone: "ERSS-112-NAT",
  },
  // --- South Zone ---
  {
    id: "hyderabad",
    name: "Hyderabad",
    state: "Telangana",
    region: "GHMC Region",
    coordinates: [78.4867, 17.3850],
    zoom: 12,
    cad_zone: "ERSS-112-TS",
  },
  {
    id: "bengaluru",
    name: "Bengaluru",
    state: "Karnataka",
    region: "BBMP Greater Bengaluru",
    coordinates: [77.5946, 12.9716],
    zoom: 12,
    cad_zone: "ERSS-112-KA",
  },
  {
    id: "chennai",
    name: "Chennai",
    state: "Tamil Nadu",
    region: "Greater Chennai Corp",
    coordinates: [80.2707, 13.0827],
    zoom: 12,
    cad_zone: "ERSS-112-TN",
  },
  {
    id: "vijayawada",
    name: "Vijayawada / Amaravati",
    state: "Andhra Pradesh",
    region: "CRDA Capital Region",
    coordinates: [80.6480, 16.5062],
    zoom: 13,
    cad_zone: "ERSS-112-AP",
  },
  {
    id: "visakhapatnam",
    name: "Visakhapatnam",
    state: "Andhra Pradesh",
    region: "GVMC Coastal Zone",
    coordinates: [83.2185, 17.6868],
    zoom: 12,
    cad_zone: "ERSS-112-AP",
  },
  {
    id: "kochi",
    name: "Kochi",
    state: "Kerala",
    region: "Ernakulam Metro",
    coordinates: [76.2673, 9.9312],
    zoom: 12,
    cad_zone: "ERSS-112-KL",
  },
  {
    id: "thiruvananthapuram",
    name: "Thiruvananthapuram",
    state: "Kerala",
    region: "South Kerala Command",
    coordinates: [76.9366, 8.5241],
    zoom: 12,
    cad_zone: "ERSS-112-KL",
  },
  {
    id: "coimbatore",
    name: "Coimbatore",
    state: "Tamil Nadu",
    region: "Kongu Region",
    coordinates: [76.9558, 11.0168],
    zoom: 12,
    cad_zone: "ERSS-112-TN",
  },

  // --- North Zone ---
  {
    id: "delhi",
    name: "Delhi NCR",
    state: "National Capital Region",
    region: "MCD / NDMC Metro",
    coordinates: [77.2090, 28.6139],
    zoom: 11.5,
    cad_zone: "ERSS-112-DL",
  },
  {
    id: "jaipur",
    name: "Jaipur",
    state: "Rajasthan",
    region: "JMC Heritage & Smart Zone",
    coordinates: [75.7873, 26.9124],
    zoom: 12,
    cad_zone: "ERSS-112-RJ",
  },
  {
    id: "lucknow",
    name: "Lucknow",
    state: "Uttar Pradesh",
    region: "LMC Central Corridor",
    coordinates: [80.9462, 26.8467],
    zoom: 12,
    cad_zone: "ERSS-112-UP",
  },
  {
    id: "chandigarh",
    name: "Chandigarh",
    state: "Punjab & Haryana",
    region: "Tricity Region",
    coordinates: [76.7794, 30.7333],
    zoom: 12.5,
    cad_zone: "ERSS-112-CH",
  },
  {
    id: "varanasi",
    name: "Varanasi",
    state: "Uttar Pradesh",
    region: "Ganga Basin Command",
    coordinates: [82.9739, 25.3176],
    zoom: 12.5,
    cad_zone: "ERSS-112-UP",
  },
  {
    id: "srinagar",
    name: "Srinagar",
    state: "Jammu & Kashmir",
    region: "Kashmir Valley",
    coordinates: [74.7973, 34.0837],
    zoom: 12,
    cad_zone: "ERSS-112-JK",
  },
  {
    id: "dehradun",
    name: "Dehradun",
    state: "Uttarakhand",
    region: "Doon Valley Foothills",
    coordinates: [78.0322, 30.3165],
    zoom: 12,
    cad_zone: "ERSS-112-UK",
  },

  // --- West Zone ---
  {
    id: "mumbai",
    name: "Mumbai",
    state: "Maharashtra",
    region: "BMC Island & Suburbs",
    coordinates: [72.8777, 19.0760],
    zoom: 11.5,
    cad_zone: "ERSS-112-MH",
  },
  {
    id: "pune",
    name: "Pune",
    state: "Maharashtra",
    region: "PMC / PCMC Industrial Zone",
    coordinates: [73.8567, 18.5204],
    zoom: 12,
    cad_zone: "ERSS-112-MH",
  },
  {
    id: "ahmedabad",
    name: "Ahmedabad",
    state: "Gujarat",
    region: "AMC Sabarmati Region",
    coordinates: [72.5714, 23.0225],
    zoom: 12,
    cad_zone: "ERSS-112-GJ",
  },
  {
    id: "surat",
    name: "Surat",
    state: "Gujarat",
    region: "SMC Tapi Delta",
    coordinates: [72.8311, 21.1702],
    zoom: 12,
    cad_zone: "ERSS-112-GJ",
  },
  {
    id: "indore",
    name: "Indore",
    state: "Madhya Pradesh",
    region: "IMC Malwa Hub",
    coordinates: [75.8577, 22.7196],
    zoom: 12,
    cad_zone: "ERSS-112-MP",
  },
  {
    id: "goa",
    name: "Goa (Panaji)",
    state: "Goa",
    region: "North & South Coastal Zone",
    coordinates: [73.8278, 15.4909],
    zoom: 12,
    cad_zone: "ERSS-112-GA",
  },

  // --- East & North-East Zone ---
  {
    id: "kolkata",
    name: "Kolkata",
    state: "West Bengal",
    region: "KMC Hooghly Estuary",
    coordinates: [88.3639, 22.5726],
    zoom: 12,
    cad_zone: "ERSS-112-WB",
  },
  {
    id: "bhubaneswar",
    name: "Bhubaneswar / Cuttack",
    state: "Odisha",
    region: "Mahanadi Command Zone",
    coordinates: [85.8245, 20.2961],
    zoom: 12,
    cad_zone: "ERSS-112-OD",
  },
  {
    id: "patna",
    name: "Patna",
    state: "Bihar",
    region: "PMC Gangetic Plain",
    coordinates: [85.1376, 25.5941],
    zoom: 12,
    cad_zone: "ERSS-112-BR",
  },
  {
    id: "guwahati",
    name: "Guwahati",
    state: "Assam",
    region: "Brahmaputra Valley Hub",
    coordinates: [91.7362, 26.1445],
    zoom: 12,
    cad_zone: "ERSS-112-AS",
  },
  {
    id: "ranchi",
    name: "Ranchi",
    state: "Jharkhand",
    region: "Chota Nagpur Plateau",
    coordinates: [85.3096, 23.3441],
    zoom: 12,
    cad_zone: "ERSS-112-JH",
  },
];

export const DEFAULT_LOCATION = INDIA_LOCATIONS[4]; // Default: Vijayawada / Amaravati

/** Real-time OpenStreetMap Nominatim geocoding search for ANY town, village, district in India */
export async function searchIndiaLocation(query: string): Promise<IndiaLocation[]> {
  if (!query || query.trim().length < 2) return [];
  try {
    const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&countrycodes=in&limit=6`;
    const res = await fetch(url, { headers: { "Accept-Language": "en" } });
    if (!res.ok) return [];
    const data = await res.json();
    return data.map((item: any) => ({
      id: `loc_${item.place_id}`,
      name: item.name || item.display_name.split(",")[0],
      state: item.display_name.split(",").slice(-3, -2)[0]?.trim() || "India",
      region: item.display_name,
      coordinates: [parseFloat(item.lon), parseFloat(item.lat)] as [number, number],
      zoom: 13,
      cad_zone: "ERSS-112-IND",
    }));
  } catch {
    return [];
  }
}
