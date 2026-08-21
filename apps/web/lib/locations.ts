/**
 * Andhra Pradesh Urban Locations & Municipal Registry
 * Covers all 26 districts, major metropolitan areas, smart cities, and municipal corporations of Andhra Pradesh.
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

export const AP_LOCATIONS: IndiaLocation[] = [
  {
    id: "ap_statewide",
    name: "Andhra Pradesh (Statewide)",
    state: "Andhra Pradesh",
    region: "State Command HQ",
    coordinates: [80.6480, 16.5062],
    zoom: 7.2,
    cad_zone: "ERSS-112-AP",
  },
  // ─── Capital Region & Metropolitan Hubs ───
  {
    id: "vijayawada",
    name: "Vijayawada",
    state: "Andhra Pradesh",
    region: "NTR / Krishna Hub",
    coordinates: [80.6480, 16.5062],
    zoom: 13,
    cad_zone: "VMC-112-VJA",
  },
  {
    id: "amaravati",
    name: "Amaravati",
    state: "Andhra Pradesh",
    region: "CRDA Capital City",
    coordinates: [80.5158, 16.5417],
    zoom: 13,
    cad_zone: "CRDA-112-AMR",
  },
  {
    id: "visakhapatnam",
    name: "Visakhapatnam",
    state: "Andhra Pradesh",
    region: "GVMC Coastal & IT Hub",
    coordinates: [83.2185, 17.6868],
    zoom: 12.5,
    cad_zone: "GVMC-112-VZK",
  },
  {
    id: "guntur",
    name: "Guntur",
    state: "Andhra Pradesh",
    region: "GMC Urban Region",
    coordinates: [80.4365, 16.3067],
    zoom: 13,
    cad_zone: "GMC-112-GTR",
  },

  // ─── Rayalaseema Cities ───
  {
    id: "tirupati",
    name: "Tirupati",
    state: "Andhra Pradesh",
    region: "TMC Pilgrim & Tech Center",
    coordinates: [79.4192, 13.6288],
    zoom: 13,
    cad_zone: "TMC-112-TPT",
  },
  {
    id: "kurnool",
    name: "Kurnool",
    state: "Andhra Pradesh",
    region: "KMC Rayalaseema Hub",
    coordinates: [78.0373, 15.8281],
    zoom: 13,
    cad_zone: "KMC-112-KNL",
  },
  {
    id: "kadapa",
    name: "Kadapa",
    state: "Andhra Pradesh",
    region: "YSR District Corp",
    coordinates: [78.8242, 14.4673],
    zoom: 13,
    cad_zone: "KDP-112-YSR",
  },
  {
    id: "anantapur",
    name: "Anantapur",
    state: "Andhra Pradesh",
    region: "Anantapuramu Corp",
    coordinates: [77.6006, 14.6819],
    zoom: 13,
    cad_zone: "ATP-112-ANT",
  },
  {
    id: "nandyal",
    name: "Nandyal",
    state: "Andhra Pradesh",
    region: "Nandyal District HQ",
    coordinates: [78.4836, 15.4786],
    zoom: 13.5,
    cad_zone: "NDL-112-NDL",
  },
  {
    id: "proddatur",
    name: "Proddatur",
    state: "Andhra Pradesh",
    region: "YSR Kadapa Trade Hub",
    coordinates: [78.5523, 14.7527],
    zoom: 13.5,
    cad_zone: "PDT-112-YSR",
  },
  {
    id: "chittoor",
    name: "Chittoor",
    state: "Andhra Pradesh",
    region: "Chittoor District Corp",
    coordinates: [79.1003, 13.2172],
    zoom: 13.5,
    cad_zone: "CTR-112-CTR",
  },
  {
    id: "hindupur",
    name: "Hindupur",
    state: "Andhra Pradesh",
    region: "Sri Sathya Sai Industrial",
    coordinates: [77.4920, 13.8290],
    zoom: 13.5,
    cad_zone: "HNP-112-SSS",
  },
  {
    id: "madanapalle",
    name: "Madanapalle",
    state: "Andhra Pradesh",
    region: "Annamayya Center",
    coordinates: [78.5030, 13.5560],
    zoom: 13.5,
    cad_zone: "MDP-112-ANM",
  },
  {
    id: "adoni",
    name: "Adoni",
    state: "Andhra Pradesh",
    region: "Kurnool Commercial Center",
    coordinates: [77.2728, 15.6322],
    zoom: 13.5,
    cad_zone: "ADN-112-KNL",
  },
  {
    id: "dharmavaram",
    name: "Dharmavaram",
    state: "Andhra Pradesh",
    region: "Sri Sathya Sai Center",
    coordinates: [77.7126, 14.4137],
    zoom: 13.5,
    cad_zone: "DMV-112-SSS",
  },
  {
    id: "puttaparthi",
    name: "Puttaparthi",
    state: "Andhra Pradesh",
    region: "Sri Sathya Sai HQ",
    coordinates: [77.8115, 14.1670],
    zoom: 14,
    cad_zone: "PTP-112-SSS",
  },

  // ─── Coastal Andhra Cities ───
  {
    id: "kakinada",
    name: "Kakinada",
    state: "Andhra Pradesh",
    region: "Smart Port City Corp",
    coordinates: [82.2475, 16.9891],
    zoom: 13,
    cad_zone: "KKD-112-KKD",
  },
  {
    id: "rajahmundry",
    name: "Rajahmundry",
    state: "Andhra Pradesh",
    region: "Godavari Cultural Corp",
    coordinates: [81.8040, 17.0005],
    zoom: 13,
    cad_zone: "RJY-112-EGD",
  },
  {
    id: "nellore",
    name: "Nellore",
    state: "Andhra Pradesh",
    region: "NMC Coastal Hub",
    coordinates: [79.9865, 14.4426],
    zoom: 13,
    cad_zone: "NMC-112-NLR",
  },
  {
    id: "eluru",
    name: "Eluru",
    state: "Andhra Pradesh",
    region: "Eluru District Corp",
    coordinates: [81.0952, 16.7107],
    zoom: 13,
    cad_zone: "ELR-112-ELR",
  },
  {
    id: "ongole",
    name: "Ongole",
    state: "Andhra Pradesh",
    region: "Prakasam District Corp",
    coordinates: [80.0499, 15.5057],
    zoom: 13,
    cad_zone: "OGL-112-PRK",
  },
  {
    id: "machilipatnam",
    name: "Machilipatnam",
    state: "Andhra Pradesh",
    region: "Krishna Port HQ",
    coordinates: [81.1389, 16.1875],
    zoom: 13.5,
    cad_zone: "MTM-112-KRN",
  },
  {
    id: "tenali",
    name: "Tenali",
    state: "Andhra Pradesh",
    region: "Guntur Delta Hub",
    coordinates: [80.6400, 16.2430],
    zoom: 13.5,
    cad_zone: "TNL-112-GTR",
  },
  {
    id: "bhimavaram",
    name: "Bhimavaram",
    state: "Andhra Pradesh",
    region: "West Godavari Tech Center",
    coordinates: [81.5212, 16.5449],
    zoom: 13.5,
    cad_zone: "BVM-112-WGD",
  },
  {
    id: "tadepalligudem",
    name: "Tadepalligudem",
    state: "Andhra Pradesh",
    region: "West Godavari Trade Hub",
    coordinates: [81.5268, 16.8142],
    zoom: 13.5,
    cad_zone: "TPG-112-WGD",
  },
  {
    id: "gudivada",
    name: "Gudivada",
    state: "Andhra Pradesh",
    region: "Krishna Commercial Center",
    coordinates: [80.9926, 16.4410],
    zoom: 13.5,
    cad_zone: "GDV-112-KRN",
  },
  {
    id: "narasaraopet",
    name: "Narasaraopet",
    state: "Andhra Pradesh",
    region: "Palnadu District HQ",
    coordinates: [80.0500, 16.2360],
    zoom: 13.5,
    cad_zone: "NRP-112-PLN",
  },
  {
    id: "bapatla",
    name: "Bapatla",
    state: "Andhra Pradesh",
    region: "Bapatla District HQ",
    coordinates: [80.4676, 15.9042],
    zoom: 13.5,
    cad_zone: "BPT-112-BPT",
  },

  // ─── North Coastal Andhra Cities ───
  {
    id: "vizianagaram",
    name: "Vizianagaram",
    state: "Andhra Pradesh",
    region: "Vizianagaram Corp",
    coordinates: [83.3956, 18.1067],
    zoom: 13,
    cad_zone: "VZM-112-VZM",
  },
  {
    id: "srikakulam",
    name: "Srikakulam",
    state: "Andhra Pradesh",
    region: "Srikakulam District Corp",
    coordinates: [83.8938, 18.2949],
    zoom: 13,
    cad_zone: "SKM-112-SKM",
  },
  {
    id: "anakapalli",
    name: "Anakapalli",
    state: "Andhra Pradesh",
    region: "Anakapalli Industrial",
    coordinates: [83.0039, 17.6913],
    zoom: 13.5,
    cad_zone: "ANK-112-ANK",
  },
  {
    id: "parvathipuram",
    name: "Parvathipuram",
    state: "Andhra Pradesh",
    region: "Parvathipuram Manyam HQ",
    coordinates: [83.4333, 18.7833],
    zoom: 13.5,
    cad_zone: "PVP-112-MNY",
  },
];

export const INDIA_LOCATIONS = AP_LOCATIONS;

export const DEFAULT_LOCATION: IndiaLocation = AP_LOCATIONS[1]; // Vijayawada

export async function searchIndiaLocation(query: string): Promise<IndiaLocation[]> {
  const q = query.toLowerCase().trim();
  return AP_LOCATIONS.filter(
    (l) =>
      l.name.toLowerCase().includes(q) ||
      l.region.toLowerCase().includes(q) ||
      l.state.toLowerCase().includes(q) ||
      l.cad_zone.toLowerCase().includes(q)
  );
}
