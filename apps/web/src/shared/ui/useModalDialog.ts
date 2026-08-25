import { useCallback, useEffect, useRef } from 'react';

/** 打开原生模态对话框，并在关闭或卸载后把焦点还给触发元素。 */
export function useModalDialog(onClose: () => void) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    openerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    if (dialog !== null && !dialog.open) dialog.showModal();
    return () => {
      if (dialog?.open) dialog.close();
      openerRef.current?.focus();
    };
  }, []);

  /** 先结束原生模态状态，再通知父级卸载内容。 */
  const closeDialog = useCallback(() => {
    const dialog = dialogRef.current;
    if (dialog?.open) dialog.close();
    onCloseRef.current();
  }, []);

  return { dialogRef, closeDialog };
}
