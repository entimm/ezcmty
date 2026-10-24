Component({
  options: { styleIsolation: 'apply-shared' },
  properties: {
    loading: Boolean,
    error: String,
    empty: Boolean,
    title: { type: String, value: '' },
    description: String,
    actionText: { type: String, value: '重试' },
    icon: { type: String, value: 'inbox' },
  },
  methods: {
    retry() {
      this.triggerEvent('retry');
      this.triggerEvent('action');
    },
  },
});
