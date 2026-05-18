/**
 * Selective clone from short-video-maker (https://github.com/gyoridavid/short-video-maker)
 * Only the types relevant to Pexels video search and music selection.
 * Original file: src/types/shorts.ts
 * License: MIT (see LICENSE file in this directory)
 */

export enum MusicMoodEnum {
  sad = "sad",
  melancholic = "melancholic",
  happy = "happy",
  euphoric = "euphoric/high",
  excited = "excited",
  chill = "chill",
  uneasy = "uneasy",
  angry = "angry",
  dark = "dark",
  hopeful = "hopeful",
  contemplative = "contemplative",
  funny = "funny/quirky",
}

export enum OrientationEnum {
  landscape = "landscape",
  portrait = "portrait",
}

export type Video = {
  id: string;
  url: string;
  width: number;
  height: number;
};

export type Music = {
  file: string;
  start: number;
  end: number;
  mood: string;
};

export type MusicForVideo = Music & {
  url: string;
};

export type MusicTag = `${MusicMoodEnum}`;
