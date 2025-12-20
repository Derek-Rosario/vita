// Basic Service Worker for Web Push notifications
self.addEventListener('install', (event) => {
	self.skipWaiting();
});

self.addEventListener('activate', (event) => {
	event.waitUntil(self.clients.claim());
});

// Handle incoming push messages
self.addEventListener('push', (event) => {
	let data = {};
	try {
		if (event.data) {
			data = event.data.json();
		}
	} catch (e) {
		try {
			data = { title: 'Notification', body: event.data.text() };
		} catch (_) {
			data = { title: 'Notification', body: '' };
		}
	}

	const title = data.title || 'Vita';
	const options = {
		body: data.body || '',
		icon: data.icon || '/static/icons/icon-192.png',
		badge: data.badge || '/static/icons/badge-72.png',
		data: data.url ? { url: data.url } : {},
	};

	event.waitUntil(self.registration.showNotification(title, options));
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
	event.notification.close();
	const url = event.notification?.data?.url;
	if (url) {
		event.waitUntil(
			self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
				for (const client of clientList) {
					if ('focus' in client) {
						client.navigate(url);
						return client.focus();
					}
				}
				if (self.clients.openWindow) {
					return self.clients.openWindow(url);
				}
			})
		);
	}
});
