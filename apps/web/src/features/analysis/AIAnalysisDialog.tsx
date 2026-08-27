import { useModalDialog } from '../../shared/ui/useModalDialog';
import type { AnalysisTarget } from './api';
import { InvestmentAnalysisPanel } from './InvestmentAnalysisPanel';
import './analysis.css';

interface AIAnalysisDialogProps {
  instrument: AnalysisTarget;
  onClose: () => void;
}

/** 用右侧抽屉承载可复用分析面板，并保留原生对话框的焦点管理。 */
export function AIAnalysisDialog({ instrument, onClose }: AIAnalysisDialogProps) {
  const { dialogRef, closeDialog } = useModalDialog(onClose);

  return (
    <dialog
      className="ai-analysis-drawer"
      ref={dialogRef}
      aria-label={`${instrument.name} AI 分析`}
      onCancel={(event) => { event.preventDefault(); closeDialog(); }}
    >
      <InvestmentAnalysisPanel instrument={instrument} onClose={closeDialog} />
    </dialog>
  );
}
