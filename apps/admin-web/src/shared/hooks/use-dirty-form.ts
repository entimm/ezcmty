import { useEffect, useRef, useState } from 'react';
import { App } from 'antd';
import { history } from '@umijs/max';

export function useDirtyForm() {
  const [dirty, setDirty] = useState(false);
  const cleanupRef = useRef<(() => void) | undefined>(undefined);
  const { modal } = App.useApp();
  useEffect(() => {
    if (!dirty) return;
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', unload);
    const unblock = history?.block((transition) => {
      modal.confirm({
        title: '放弃未保存的修改？',
        onOk: () => {
          unblock();
          transition.retry();
        },
      });
    });
    const cleanup = () => {
      unblock?.();
      window.removeEventListener('beforeunload', unload);
      cleanupRef.current = undefined;
    };
    cleanupRef.current = cleanup;
    return cleanup;
  }, [dirty, modal]);
  return {
    changed: () => setDirty(true),
    reset: () => {
      // A successful save can navigate before React runs the effect cleanup.
      cleanupRef.current?.();
      setDirty(false);
    },
    close: (done: () => void) => {
      if (dirty) modal.confirm({ title: '放弃未保存的修改？', onOk: done });
      else done();
    },
  };
}
