// frontend/src/api.js
import axios from "axios";

const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL || "http://localhost:8000"
});

const normalizeEmails = (obj) => {
  if (Array.isArray(obj)) {
    obj.forEach((item) => normalizeEmails(item));
    return obj;
  }
  if (obj && typeof obj === "object") {
    for (const key of Object.keys(obj)) {
      const val = obj[key];
      if (typeof val === "string" && key.toLowerCase().includes("email")) {
        obj[key] = val.toLowerCase();
      } else if (val && typeof val === "object") {
        normalizeEmails(val);
      }
    }
  }
  return obj;
};

const getLocalStorage = () => {
  if (typeof window === "undefined" || !window.localStorage) {
    return null;
  }
  return window.localStorage;
};

export const getAccessToken = () => {
  const storage = getLocalStorage();
  return storage ? storage.getItem("token") : null;
};

export const getRefreshToken = () => {
  const storage = getLocalStorage();
  return storage ? storage.getItem("refreshToken") : null;
};

export const storeTokens = (accessToken, refreshToken) => {
  const storage = getLocalStorage();
  if (!storage) return;
  if (accessToken) {
    storage.setItem("token", accessToken);
  }
  if (refreshToken) {
    storage.setItem("refreshToken", refreshToken);
  }
};

export const clearStoredTokens = () => {
  const storage = getLocalStorage();
  if (!storage) return;
  storage.removeItem("token");
  storage.removeItem("refreshToken");
};

const subscribers = [];
let refreshPromise = null;

const addSubscriber = (callback) => {
  subscribers.push(callback);
};

const notifySubscribers = (error, accessToken) => {
  while (subscribers.length) {
    const subscriber = subscribers.shift();
    if (subscriber) {
      subscriber(error, accessToken);
    }
  }
};

const performRefresh = async (refreshToken) => {
  try {
    const resp = await api.post(
      "/refresh",
      { refresh_token: refreshToken },
      { skipAuthRefresh: true, _skipAuthToken: true }
    );
    const newAccess = resp.data.token || resp.data.access_token;
    const newRefresh = resp.data.refresh_token || resp.data.refreshToken;
    storeTokens(newAccess, newRefresh);
    notifySubscribers(null, newAccess);
    return newAccess;
  } catch (err) {
    clearStoredTokens();
    notifySubscribers(err, null);
    throw err;
  } finally {
    refreshPromise = null;
  }
};

if (api.interceptors?.request) {
  api.interceptors.request.use((config) => {
    config.data = normalizeEmails(config.data);
    config.params = normalizeEmails(config.params);

    if (!config._skipAuthToken) {
      const accessToken = getAccessToken();
      if (accessToken) {
        config.headers = config.headers || {};
        config.headers.Authorization = `Bearer ${accessToken}`;
      }
    }

    return config;
  });
}

if (api.interceptors?.response) {
  api.interceptors.response.use(
    (response) => response,
    async (error) => {
      const { response, config } = error;
      if (!response || response.status !== 401 || config?.skipAuthRefresh || config?._retry) {
        return Promise.reject(error);
      }

      const refreshToken = getRefreshToken();
      if (!refreshToken) {
        clearStoredTokens();
        return Promise.reject(error);
      }

      const retryOriginalRequest = new Promise((resolve, reject) => {
        addSubscriber((refreshErr, newAccessToken) => {
          if (refreshErr || !newAccessToken) {
            reject(refreshErr || error);
            return;
          }
          config._retry = true;
          config.headers = config.headers || {};
          config.headers.Authorization = `Bearer ${newAccessToken}`;
          resolve(api(config));
        });
      });

      if (!refreshPromise) {
        refreshPromise = performRefresh(refreshToken);
      }

      try {
        await refreshPromise;
        return retryOriginalRequest;
      } catch (refreshErr) {
        return Promise.reject(refreshErr);
      }
    }
  );
}

export default api;
