/**
 * Gacha Item Icon Mappings and Utilities (Take 2)
 */

const GENSHIN_BASE = 'https://api.ambr.top/assets/UI/UI_AvatarIcon_';
const STARRAIL_BASE = 'https://patchwiki.biligame.com/images/sr/';

// Popular character names to asset suffixes
const ICON_MAP_GENSHIN: Record<string, string> = {
  '雷电将军': 'Raiden.png',
  '纳西妲': 'Nahida.png',
  '钟离': 'Zhongli.png',
  '温迪': 'Venti.png',
  '胡桃': 'Hutao.png',
  '神里绫华': 'Ayaka.png',
  '那维莱特': 'Neuvillette.png',
  '芙宁娜': 'Furina.png',
  '夜兰': 'Yelan.png',
  '万叶': 'Kazusa.png', // Maple leaf mascot? Actually UI_AvatarIcon_Kazuha.png
  '枫原万叶': 'Kazuha.png',
  '珊瑚宫心海': 'Kokomi.png',
  '宵宫': 'Yoimiya.png',
  '刻晴': 'Keqing.png',
  '莫娜': 'Mona.png',
  '琴': 'Qin.png',
  '迪卢克': 'Diluc.png',
  '七七': 'Nana.png',
  '提纳里': 'Tighnari.png',
  '迪希雅': 'Dehya.png',
};

const ICON_MAP_STARRAIL: Record<string, string> = {
  '希儿': '7/7b/97yisntndb8m3y0f9id086on29v770b.png',
  '景元': '8/87/nmph3w4qsqj0k5g1t8x1r6z17a0t9id.png',
  '饮月': '1/14/l7r7r7l7r7p7r7t7r7x7r817r857r89.png',
  '卡芙卡': '0/07/p7h7p7r7p7v7p7z7p837p877p8b7p8f.png',
  '流萤': 'f/f6/lp7r7r7p7v7z7p837p877p8b7p8f7p8j.png',
  '黄泉': 'f/fc/f7j7p7r7v7z7p837p877p8b7p8f7p8j.png',
  '砂金': '9/90/p7j7p7r7v7z7p837p877p8b7p8f7p8j.png',
};

export function getItemIconUrl(name: string, game: string): string | null {
  if (game === 'genshin' && ICON_MAP_GENSHIN[name]) {
    return `${GENSHIN_BASE}${ICON_MAP_GENSHIN[name]}`;
  }
  if (game === 'starrail' && ICON_MAP_STARRAIL[name]) {
    return `${STARRAIL_BASE}${ICON_MAP_STARRAIL[name]}`;
  }
  return null;
}

export function getRankColor(rank: string | number): string {
  const r = typeof rank === 'string' ? parseInt(rank) : rank;
  if (r === 5) return '#f3d144';
  if (r === 4) return '#af89f5';
  return '#5196f7';
}

export function getItemInitial(name: string): string {
  if (!name) return '?';
  return name.charAt(0);
}
