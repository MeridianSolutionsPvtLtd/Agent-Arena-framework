import React from 'react';
import Skeleton from './Skeleton';

export default function SkeletonStatCard() {
  return (
    <div className="p-8 border border-border/40 bg-white rounded-xl relative overflow-hidden shadow-xs">
      <div className="flex items-center justify-between mb-4">
        <Skeleton variant="rounded" className="w-10 h-10 rounded-xl" />
        <Skeleton variant="rounded" className="w-14 h-5 rounded-md" />
      </div>
      <Skeleton variant="text" className="h-3 w-28 mb-3 mt-4" />
      <Skeleton variant="text" className="h-8 w-24 mb-3" />
      <Skeleton variant="text" className="h-3 w-20" />
    </div>
  );
}
