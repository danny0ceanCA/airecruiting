// Utility to safely load Google Maps JS API only once
export default function loadGoogleMaps(callback) {
  if (window.google && window.google.maps) {
    if (typeof callback === 'function') callback();
    return;
  }

  const existing = document.getElementById('google-maps-script');
  if (existing) {
    if (typeof callback === 'function') {
      if (existing.getAttribute('data-loaded')) {
        callback();
      } else {
        existing.addEventListener('load', callback, { once: true });
      }
    }
    return;
  }

  const script = document.createElement('script');
  script.id = 'google-maps-script';
  script.src = `https://maps.googleapis.com/maps/api/js?key=${process.env.REACT_APP_GOOGLE_KEY}&libraries=places`;
  script.async = true;
  if (typeof callback === 'function') {
    script.addEventListener('load', () => {
      script.setAttribute('data-loaded', 'true');
      callback();
    }, { once: true });
  } else {
    script.addEventListener('load', () => {
      script.setAttribute('data-loaded', 'true');
    }, { once: true });
  }
  document.body.appendChild(script);
}
