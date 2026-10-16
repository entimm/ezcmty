Component({
  properties: {
    loading: Boolean,
    error: String,
    empty: Boolean,
    message: { type: String, value: '暂时还没有记录' },
  },
  methods: {
    retry() {
      this.triggerEvent('retry');
    },
  },
});
