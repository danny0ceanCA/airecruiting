import React from 'react';
import { Navigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import { getAccessToken, getRefreshToken } from './api';

function ProtectedRoute({ children }) {
  const token = getAccessToken();
  const refreshToken = getRefreshToken();

  if (!token && !refreshToken) {
    return <Navigate to="/login" replace />;
  }

  if (token) {
    try {
      const { exp } = jwtDecode(token);
      if (exp && Date.now() >= exp * 1000 && !refreshToken) {
        return <Navigate to="/login" replace />;
      }
    } catch (err) {
      if (!refreshToken) {
        return <Navigate to="/login" replace />;
      }
    }
  }

  return children;
}

export default ProtectedRoute;
