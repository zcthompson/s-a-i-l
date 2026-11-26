import type { AmountBasis, Deal, DealType } from '../types/deals';

export const BASIS_LABELS: Record<AmountBasis, string> = { one_time: 'One-time', acv: 'ACV', tcv: 'TCV', mrr: 'MRR' };
export const TYPE_LABELS: Record<DealType, string> = { new: 'New', expansion: 'Expansion', renewal: 'Renewal', services: 'Services' };

export function formatDealAmount(deal: Pick<Deal, 'amount' | 'amount_basis'>): string {
  if (!deal.amount) return 'Amount not recorded';
  const { minor, currency } = deal.amount;
  let text: string;
  try {
    text = new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(minor / 100);
  } catch {
    text = `${currency} ${(minor / 100).toFixed(2)}`;
  }
  return deal.amount_basis ? `${text} · ${BASIS_LABELS[deal.amount_basis]}` : text;
}

export function probabilityText(deal: Pick<Deal, 'probability' | 'suggested_probability'>): string {
  if (deal.probability != null) return `${deal.probability}%`;
  return deal.suggested_probability != null ? `Not set (stage suggests ${deal.suggested_probability}%)` : 'Not set';
}

/** Decimal major-unit text → integer minor units; null when blank; NaN when invalid. */
export function toMinor(text: string): number | null {
  const t = text.trim().replace(/,/g, '');
  if (!t) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return Number.NaN;
  return Math.round(Number(t) * 100);
}

