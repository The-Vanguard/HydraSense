// Tier vocabulary: architecture colours (Red/Orange/Yellow/Green) with the plain words used on screen.
export const TIERS = ['Red', 'Orange', 'Yellow', 'Green'];
export const TIER_WORD = { Red: 'High', Orange: 'Moderate', Yellow: 'Watch', Green: 'Safe' };
export const TIER_COLOR = { Red: '#dc2626', Orange: '#ea580c', Yellow: '#ca8a04', Green: '#16a34a' };
export const TIER_CLASS = { Red: 'red', Orange: 'orange', Yellow: 'yellow', Green: 'green' };
export const tierLabel = (t) => (t ? `${TIER_WORD[t] || t} (${t})` : 'not scored');
export const tierFromScore = (s) => (s == null ? null : s >= 75 ? 'Red' : s >= 55 ? 'Orange' : s >= 30 ? 'Yellow' : 'Green');

export const fmtAgo = (iso) => {
  if (!iso) return '—';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};
export const fmtIST = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short',
      year: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' IST';
  } catch { return iso; }
};

export const REGION_NAMES = {
  'all-india': 'India / National Overview',
  'wayanad-kl': 'Wayanad, Kerala', 'idukki-kl': 'Idukki, Kerala', 'nilgiris-tn': 'Nilgiris, Tamil Nadu',
  'rudraprayag-uk': 'Rudraprayag, Uttarakhand', 'chamoli-uk': 'Chamoli, Uttarakhand', 'kullu-hp': 'Kullu, Himachal Pradesh',
  'mangan-sk': 'Mangan, Sikkim', 'darjeeling-wb': 'Darjeeling, West Bengal', 'ribhoi-ml': 'Ri-Bhoi, Meghalaya',
  'dhemaji-as': 'Dhemaji, Assam',
};
export const STATE_VIEWS = [
  { label: 'Tamil Nadu', regions: ['nilgiris-tn'] },
  { label: 'Kerala', regions: ['idukki-kl', 'wayanad-kl'] },
  { label: 'Uttarakhand', regions: ['rudraprayag-uk', 'chamoli-uk'] },
  { label: 'Himachal Pradesh', regions: ['kullu-hp'] },
  { label: 'Sikkim / West Bengal', regions: ['mangan-sk', 'darjeeling-wb'] },
  { label: 'Northeast', regions: ['ribhoi-ml', 'dhemaji-as'] },
];
export const CORRIDORS = [
  { label: 'Nilgiris (TN)', code: 'nilgiris-tn' }, { label: 'Wayanad (KL)', code: 'wayanad-kl' },
  { label: 'Kedarnath (UK)', code: 'rudraprayag-uk' }, { label: 'Manali (HP)', code: 'kullu-hp' },
  { label: 'Darjeeling (WB)', code: 'darjeeling-wb' }, { label: 'Mangan (SK)', code: 'mangan-sk' },
];
export const FEATURE_LABEL = {
  rain_trigger: 'Rainfall trigger (I–D threshold)', p_fs_lt1: 'Slope stability P(FS<1)', hand_m: 'Height above drainage (flood)',
  slope: 'Slope / terrain', slope_deg: 'Slope / terrain', soil_saturation_ratio: 'Soil saturation', rainfall_6h: 'Rainfall (6 h)',
  rainfall_24h: 'Rainfall (24 h)', factor_of_safety: 'Factor of safety (FS)', historical_event_count_500m: 'Historical events',
};
