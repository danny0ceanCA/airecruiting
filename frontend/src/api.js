// frontend/src/api.js
import axios from "axios";

const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL || "http://localhost:8000"
});

if (api.interceptors?.request) {
  api.interceptors.request.use((config) => {
    const normalize = (obj) => {
      if (obj && typeof obj === "object") {
        for (const key of Object.keys(obj)) {
          const val = obj[key];
          if (typeof val === "string" && key.toLowerCase().includes("email")) {
            obj[key] = val.toLowerCase();
          }
        }
      }
      return obj;
    };
    config.data = normalize(config.data);
    config.params = normalize(config.params);
    return config;
  });
}

export default api;
