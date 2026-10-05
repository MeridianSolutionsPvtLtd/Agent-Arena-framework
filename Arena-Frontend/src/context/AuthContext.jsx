import React, { createContext, useContext, useState, useEffect } from 'react';
import { getAccessToken, clearTokens } from '../services/api';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const savedUser = localStorage.getItem('meridian_user');
    const token = getAccessToken();
    if (savedUser && token) return JSON.parse(savedUser);
    return null;
  });

  const login = (userData) => {
    setUser(userData);
    localStorage.setItem('meridian_user', JSON.stringify(userData));
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem('meridian_user');
    clearTokens();
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
