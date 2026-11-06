/**
 * dsh-garment-studio 的浏览器侧半边：只做两件事，不碰 DSH 内部实现。
 *
 *   1. 在左侧栏注册一个图标（sidebar.panellist）；
 *   2. 在 main 槽位注册同 id 的面板页，内容是一个整页 iframe，指向宿主侧的
 *      /garment-studio/panel（真正的界面由 studio/server.py 这个普通 HTTP 服务提供）。
 *
 * 这样即使 DSH 的 slot 约定变了，最多是这个面板空掉，不会牵连 DSH 本身；
 * 同一个界面也可以在浏览器里直接开 http://127.0.0.1:8765/ 使用。
 */
window.__ModuleLoader__.load({
	id: 'dsh-garment-studio',
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

		const react = require('react');
		const h = react.createElement;
		const PANEL_ID = 'garment-studio';

		/** 侧栏图标：一件挂着的衣服。 */
		function GarmentIcon(props) {
			const size = (props && props.size) || 20;
			return h(
				'svg',
				{
					width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
					stroke: 'currentColor', strokeWidth: 1.6,
					strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': 'true',
				},
				h('path', { d: 'M12 3.4a2 2 0 0 0-2 2c0 .9.6 1.4 1.1 1.8' }),
				h('path', { d: 'M12 7.2 4 12.2v3.2l8 2.4 8-2.4v-3.2L12 7.2Z' }),
				h('path', { d: 'M8.4 20.4h7.2' }),
			);
		}

		/** 主面板：整页 iframe，内容来自宿主路由。 */
		function GarmentPanel() {
			return h('iframe', {
				src: '/garment-studio/panel',
				title: 'Garment Studio',
				style: { width: '100%', height: '100%', border: '0', display: 'block', background: '#0f1116' },
			});
		}

		const inject = ['slots'];

		function apply(ctx) {
			ctx.slots.inject('sidebar.panellist', () =>
				ctx.slots.register(
					{ name: 'sidebar.panellist', id: PANEL_ID, order: 60, label: () => 'Garment Studio' },
					GarmentIcon,
				),
			);
			ctx.slots.inject('main', () =>
				ctx.slots.register({ name: 'main', key: PANEL_ID, inject: () => ({}) }, GarmentPanel),
			);
		}

		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	},
});
