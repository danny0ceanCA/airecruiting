// frontend/src/api.js
import axios from "axios";

const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL || "http://localhost:8000"
});

export const approveUser = (email, role, config = {}) =>
  api.post("/approve", { email, role }, config);

export default api;
