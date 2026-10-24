Component({
  properties: {
    name: { type: String, value: 'house' },
    size: { type: Number, value: 40 },
    tone: { type: String, value: 'ink' },
  },
  data: { source: '/assets/icons/house.svg' },
  observers: {
    'name,tone'(name: string, tone: string) {
      const safe = /^[a-z0-9-]+$/.test(name) ? name : 'circle-help';
      this.setData({
        source:
          '/assets/icons/' +
          safe +
          (['green', 'blue', 'orange', 'muted'].includes(tone)
            ? '-' + tone
            : '') +
          '.svg',
      });
    },
  },
  methods: {
    fallback() {
      if (this.data.source !== '/assets/icons/circle-help.svg')
        this.setData({ source: '/assets/icons/circle-help.svg' });
    },
  },
});
