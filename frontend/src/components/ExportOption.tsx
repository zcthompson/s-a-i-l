import { useId } from 'react';
import { ActionButton } from './ActionButton';
import { SectionIcon } from './SectionIcon';

/** A report format is a neutral choice, not a destructive/status action. */
export function ExportOption({ label, title, description, icon, busy, disabled, suggested = false, onClick }: {
  label: string; title: string; description: string; icon: string;
  suggested?: boolean; busy: boolean; disabled: boolean; onClick: () => void;
}) {
  const descriptionId = useId();
  return <ActionButton aria-label={label} aria-describedby={descriptionId} variant="secondary" data-layout="export-option" data-suggested={suggested || undefined} busy={busy} disabled={disabled} onClick={onClick} icon={<SectionIcon name={icon} />}>
    <span data-ui="export-copy"><span data-ui="export-title">{title}{suggested && <span data-ui="format-hint">Suggested format</span>}</span><span id={descriptionId} data-ui="export-description">{description}</span></span>
  </ActionButton>;
}
