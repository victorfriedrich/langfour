'use client';

import React from 'react';

import YouTubeVideoGrid from './YouTubeVideoGrid';
import ProtectedRoute from './ProtectedRoute';

/**
 * Rendered only by app/page.tsx, i.e. the "/" route, so there is nothing to
 * dispatch on: every other path in the app is served by its own App Router
 * page.
 */
const AppClient: React.FC = () => (
  <ProtectedRoute>
    <YouTubeVideoGrid />
  </ProtectedRoute>
);

export default AppClient;
