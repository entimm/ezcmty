Component({
  options: { multipleSlots: true, styleIsolation: 'apply-shared' },
  properties: {
    show: Boolean,
    title: String,
    busy: Boolean,
    confirmText: { type: String, value: '确认' },
    cancelText: { type: String, value: '取消' },
    danger: Boolean,
    customFooter: Boolean,
    hideCancel: Boolean,
  },
  methods: {
    noop() {},
    close() {
      if (!this.data.busy) this.triggerEvent('close');
    },
    confirm() {
      if (!this.data.busy) this.triggerEvent('confirm');
    },
  },
});
