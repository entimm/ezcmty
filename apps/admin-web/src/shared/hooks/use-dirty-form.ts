import { useEffect, useState } from 'react';
import { App } from 'antd';
import { history } from '@umijs/max';

export function useDirtyForm() {
  const [dirty, setDirty] = useState(false);
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
    return () => {
      unblock?.();
      window.removeEventListener('beforeunload', unload);
    };
  }, [dirty, modal]);
  return {
    changed: () => setDirty(true),
    reset: () => setDirty(false),
    close: (done: () => void) => {
      if (dirty) modal.confirm({ title: '放弃未保存的修改？', onOk: done });
      else done();
    },
  };
}
