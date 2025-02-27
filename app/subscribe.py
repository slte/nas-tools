import json
from threading import Lock

import log
from app.downloader import Downloader
from app.media.douban import DouBan
from app.helper import DbHelper, MetaHelper
from app.media import MetaInfo, Media
from app.message import Message
from app.searcher import Searcher
from app.utils.types import MediaType, SearchType

lock = Lock()


class Subscribe:
    dbhelper = None
    metahelper = None
    searcher = None
    message = None
    media = None
    downloader = None

    def __init__(self):
        self.dbhelper = DbHelper()
        self.metahelper = MetaHelper()
        self.searcher = Searcher()
        self.message = Message()
        self.media = Media()
        self.downloader = Downloader()

    def add_rss_subscribe(self, mtype, name, year,
                          season=None,
                          fuzzy_match=False,
                          doubanid=None,
                          tmdbid=None,
                          rss_sites=None,
                          search_sites=None,
                          over_edition=False,
                          filter_restype=None,
                          filter_pix=None,
                          filter_team=None,
                          filter_rule=None,
                          save_path=None,
                          download_setting=None,
                          total_ep=None,
                          current_ep=None,
                          state="D",
                          rssid=None):
        """
        添加电影、电视剧订阅
        :param mtype: 类型，电影、电视剧、动漫
        :param name: 标题
        :param year: 年份，如要是剧集需要是首播年份
        :param season: 第几季，数字
        :param fuzzy_match: 是否模糊匹配
        :param doubanid: 豆瓣ID，有此ID时从豆瓣查询信息
        :param tmdbid: TMDBID，有此ID时优先使用ID查询TMDB信息，没有则使用名称查询
        :param rss_sites: 订阅站点列表，为空则表示全部站点
        :param search_sites: 搜索站点列表，为空则表示全部站点
        :param over_edition: 是否选版
        :param filter_restype: 质量过滤
        :param filter_pix: 分辨率过滤
        :param filter_team: 制作组/字幕组过滤
        :param filter_rule: 关键字过滤
        :param save_path: 保存路径
        :param download_setting: 下载设置
        :param state: 添加订阅时的状态
        :param rssid: 修改订阅时传入
        :param total_ep: 总集数
        :param current_ep: 开始订阅集数
        :return: 错误码：0代表成功，错误信息
        """
        if not name:
            return -1, "标题或类型有误", None
        year = int(year) if str(year).isdigit() else ""
        rss_sites = rss_sites or []
        search_sites = search_sites or []
        over_edition = 1 if over_edition else 0
        filter_rule = int(filter_rule) if str(filter_rule).isdigit() else None
        total_ep = int(total_ep) if str(total_ep).isdigit() else None
        current_ep = int(current_ep) if str(current_ep).isdigit() else None
        download_setting = int(download_setting) if str(download_setting).isdigit() else -1
        fuzzy_match = True if fuzzy_match else False
        # 检索媒体信息
        if not fuzzy_match:
            # 精确匹配
            media = Media()
            # 根据TMDBID查询，从推荐加订阅的情况
            if season:
                title = "%s %s 第%s季".strip() % (name, year, season)
            else:
                title = "%s %s".strip() % (name, year)
            if tmdbid:
                # 根据TMDBID查询
                media_info = MetaInfo(title=title, mtype=mtype)
                media_info.set_tmdb_info(media.get_tmdb_info(mtype=mtype, tmdbid=tmdbid))
                if not media_info.tmdb_info:
                    return 1, "无法查询到媒体信息", None
            else:
                # 根据名称和年份查询
                media_info = media.get_media_info(title=title,
                                                  mtype=mtype,
                                                  strict=True if year else False,
                                                  cache=False)
                if media_info and media_info.tmdb_info:
                    tmdbid = media_info.tmdb_id
                elif doubanid:
                    # 先从豆瓣网页抓取（含TMDBID）
                    douban_info = DouBan().get_media_detail_from_web(doubanid)
                    if not douban_info:
                        douban_info = DouBan().get_douban_detail(doubanid=doubanid, mtype=mtype)
                    if not douban_info or douban_info.get("localized_message"):
                        return 1, "无法查询到豆瓣媒体信息", None
                    media_info = MetaInfo(title="%s %s".strip() % (douban_info.get('title'), year), mtype=mtype)
                    # 以IMDBID查询TMDB
                    if douban_info.get("imdbid"):
                        tmdbid = Media().get_tmdbid_by_imdbid(douban_info.get("imdbid"))
                        if tmdbid:
                            media_info.set_tmdb_info(Media().get_tmdb_info(mtype=mtype, tmdbid=tmdbid))
                    # 无法识别TMDB时以豆瓣信息订阅
                    if not media_info.tmdb_info:
                        media_info.title = douban_info.get('title')
                        media_info.year = douban_info.get("year")
                        media_info.type = mtype
                        media_info.backdrop_path = douban_info.get("cover_url")
                        media_info.tmdb_id = "DB:%s" % doubanid
                        media_info.overview = douban_info.get("intro")
                        media_info.total_episodes = douban_info.get("episodes_count")
                    # 合并季
                    if season:
                        media_info.begin_season = int(season)
                else:
                    return 1, "无法查询到媒体信息", None
            # 添加订阅
            if media_info.type != MediaType.MOVIE:
                if tmdbid:
                    if season or media_info.begin_season is not None:
                        season = int(season) if season else media_info.begin_season
                        total_episode = media.get_tmdb_season_episodes_num(sea=season, tmdbid=tmdbid)
                    else:
                        # 查询季及集信息
                        total_seasoninfo = media.get_tmdb_seasons_list(tmdbid=tmdbid)
                        if not total_seasoninfo:
                            return 2, "获取剧集信息失败", media_info
                        # 按季号降序排序
                        total_seasoninfo = sorted(total_seasoninfo, key=lambda x: x.get("season_number"),
                                                  reverse=True)
                        # 取最新季
                        season = total_seasoninfo[0].get("season_number")
                        total_episode = total_seasoninfo[0].get("episode_count")
                    if not total_episode:
                        return 3, "%s 获取剧集数失败，请确认该季是否存在" % media_info.get_title_string(), media_info
                    media_info.begin_season = season
                    media_info.total_episodes = total_episode
                if total_ep:
                    total = total_ep
                else:
                    total = media_info.total_episodes
                if current_ep:
                    lack = total - current_ep - 1
                else:
                    lack = total
                if rssid:
                    self.dbhelper.delete_rss_tv(rssid=rssid)
                code = self.dbhelper.insert_rss_tv(media_info=media_info,
                                                   total=total,
                                                   lack=lack,
                                                   state=state,
                                                   rss_sites=rss_sites,
                                                   search_sites=search_sites,
                                                   over_edition=over_edition,
                                                   filter_restype=filter_restype,
                                                   filter_pix=filter_pix,
                                                   filter_team=filter_team,
                                                   filter_rule=filter_rule,
                                                   save_path=save_path,
                                                   download_setting=download_setting,
                                                   total_ep=total_ep,
                                                   current_ep=current_ep,
                                                   fuzzy_match=0,
                                                   desc=media_info.overview,
                                                   note=self.gen_rss_note(media_info))
            else:
                if rssid:
                    self.dbhelper.delete_rss_movie(rssid=rssid)
                code = self.dbhelper.insert_rss_movie(media_info=media_info,
                                                      state=state,
                                                      rss_sites=rss_sites,
                                                      search_sites=search_sites,
                                                      over_edition=over_edition,
                                                      filter_restype=filter_restype,
                                                      filter_pix=filter_pix,
                                                      filter_team=filter_team,
                                                      filter_rule=filter_rule,
                                                      save_path=save_path,
                                                      download_setting=download_setting,
                                                      fuzzy_match=0,
                                                      desc=media_info.overview,
                                                      note=self.gen_rss_note(media_info))
        else:
            # 模糊匹配
            media_info = MetaInfo(title=name, mtype=mtype)
            media_info.title = name
            media_info.type = mtype
            if season:
                media_info.begin_season = int(season)
            if mtype == MediaType.MOVIE:
                if rssid:
                    self.dbhelper.delete_rss_movie(rssid=rssid)
                code = self.dbhelper.insert_rss_movie(media_info=media_info,
                                                      state="R",
                                                      rss_sites=rss_sites,
                                                      search_sites=search_sites,
                                                      over_edition=over_edition,
                                                      filter_restype=filter_restype,
                                                      filter_pix=filter_pix,
                                                      filter_team=filter_team,
                                                      filter_rule=filter_rule,
                                                      save_path=save_path,
                                                      download_setting=download_setting,
                                                      fuzzy_match=1)
            else:
                if rssid:
                    self.dbhelper.delete_rss_tv(rssid=rssid)
                code = self.dbhelper.insert_rss_tv(media_info=media_info,
                                                   total=0,
                                                   lack=0,
                                                   state="R",
                                                   rss_sites=rss_sites,
                                                   search_sites=search_sites,
                                                   over_edition=over_edition,
                                                   filter_restype=filter_restype,
                                                   filter_pix=filter_pix,
                                                   filter_team=filter_team,
                                                   filter_rule=filter_rule,
                                                   save_path=save_path,
                                                   download_setting=download_setting,
                                                   fuzzy_match=1)

        if code == 0:
            return code, "添加订阅成功", media_info
        elif code == 9:
            return code, "订阅已存在", media_info
        else:
            return code, "添加订阅失败", media_info

    def finish_rss_subscribe(self, rtype, rssid, media):
        """
        完成订阅
        :param rtype: 订阅类型
        :param rssid: 订阅ID
        :param media: 识别的媒体信息，发送消息使用
        """
        if not rtype or not rssid or not media:
            return
        # 电影订阅
        if rtype == "MOV":
            # 查询电影RSS数据
            rss = self.dbhelper.get_rss_movies(rssid=rssid)
            if not rss:
                return
            # 登记订阅历史
            self.dbhelper.insert_rss_history(rssid=rssid,
                                             rtype=rtype,
                                             name=rss[0].NAME,
                                             year=rss[0].YEAR,
                                             tmdbid=rss[0].TMDBID,
                                             image=media.get_poster_image(),
                                             desc=media.overview)

            # 删除订阅
            self.dbhelper.delete_rss_movie(rssid=rssid)

        # 电视剧订阅
        else:
            # 查询电视剧RSS数据
            rss = self.dbhelper.get_rss_tvs(rssid=rssid)
            if not rss:
                return
            total = rss[0].TOTAL_EP
            # 登记订阅历史
            self.dbhelper.insert_rss_history(rssid=rssid,
                                             rtype=rtype,
                                             name=rss[0].NAME,
                                             year=rss[0].YEAR,
                                             season=rss[0].SEASON,
                                             tmdbid=rss[0].TMDBID,
                                             image=media.get_poster_image(),
                                             desc=media.overview,
                                             total=total if total else rss[0].TOTAL,
                                             start=rss[0].CURRENT_EP)
            # 删除订阅
            self.dbhelper.delete_rss_tv(rssid=rssid)

        # 发送订阅完成的消息
        if media:
            Message().send_rss_finished_message(media_info=media)

    def get_subscribe_movies(self, rid=None, state=None):
        """
        获取电影订阅
        """
        ret_dict = {}
        rss_movies = self.dbhelper.get_rss_movies(rssid=rid, state=state)
        for rss_movie in rss_movies:
            desc = rss_movie.DESC
            note = rss_movie.NOTE
            tmdbid = rss_movie.TMDBID
            rss_sites = rss_movie.RSS_SITES
            rss_sites = json.loads(rss_sites) if rss_sites else []
            search_sites = rss_movie.SEARCH_SITES
            search_sites = json.loads(search_sites) if search_sites else []
            over_edition = True if rss_movie.OVER_EDITION == 1 else False
            filter_restype = rss_movie.FILTER_RESTYPE
            filter_pix = rss_movie.FILTER_PIX
            filter_team = rss_movie.FILTER_TEAM
            filter_rule = rss_movie.FILTER_RULE
            download_setting = rss_movie.DOWNLOAD_SETTING
            save_path = rss_movie.SAVE_PATH
            fuzzy_match = True if rss_movie.FUZZY_MATCH == 1 else False
            # 兼容旧配置
            if desc and desc.find('{') != -1:
                desc = self.__parse_rss_desc(desc)
                rss_sites = desc.get("rss_sites")
                search_sites = desc.get("search_sites")
                over_edition = True if desc.get("over_edition") == 'Y' else False
                filter_restype = desc.get("restype")
                filter_pix = desc.get("pix")
                filter_team = desc.get("team")
                filter_rule = desc.get("rule")
                download_setting = -1
                save_path = ""
                fuzzy_match = False if tmdbid else True
            if note:
                note_info = self.__parse_rss_desc(note)
            else:
                note_info = {}
            ret_dict[str(rss_movie.ID)] = {
                "id": rss_movie.ID,
                "name": rss_movie.NAME,
                "year": rss_movie.YEAR,
                "tmdbid": rss_movie.TMDBID,
                "image": rss_movie.IMAGE,
                "overview": rss_movie.DESC,
                "rss_sites": rss_sites,
                "search_sites": search_sites,
                "over_edition": over_edition,
                "filter_restype": filter_restype,
                "filter_pix": filter_pix,
                "filter_team": filter_team,
                "filter_rule": filter_rule,
                "save_path": save_path,
                "download_setting": download_setting,
                "fuzzy_match": fuzzy_match,
                "state": rss_movie.STATE,
                "poster": note_info.get("poster"),
                "release_date": note_info.get("release_date"),
                "vote": note_info.get("vote")

            }
        return ret_dict

    def get_subscribe_tvs(self, rid=None, state=None):
        ret_dict = {}
        rss_tvs = self.dbhelper.get_rss_tvs(rssid=rid, state=state)
        for rss_tv in rss_tvs:
            desc = rss_tv.DESC
            note = rss_tv.NOTE
            tmdbid = rss_tv.TMDBID
            rss_sites = json.loads(rss_tv.RSS_SITES) if rss_tv.RSS_SITES else []
            search_sites = json.loads(rss_tv.SEARCH_SITES) if rss_tv.SEARCH_SITES else []
            over_edition = True if rss_tv.OVER_EDITION == 1 else False
            filter_restype = rss_tv.FILTER_RESTYPE
            filter_pix = rss_tv.FILTER_PIX
            filter_team = rss_tv.FILTER_TEAM
            filter_rule = rss_tv.FILTER_RULE
            download_setting = rss_tv.DOWNLOAD_SETTING
            save_path = rss_tv.SAVE_PATH
            total_ep = rss_tv.TOTAL_EP
            current_ep = rss_tv.CURRENT_EP
            fuzzy_match = True if rss_tv.FUZZY_MATCH == 1 else False
            # 兼容旧配置
            if desc and desc.find('{') != -1:
                desc = self.__parse_rss_desc(desc)
                rss_sites = desc.get("rss_sites")
                search_sites = desc.get("search_sites")
                over_edition = True if desc.get("over_edition") == 'Y' else False
                filter_restype = desc.get("restype")
                filter_pix = desc.get("pix")
                filter_team = desc.get("team")
                filter_rule = desc.get("rule")
                save_path = ""
                download_setting = -1
                total_ep = desc.get("total")
                current_ep = desc.get("current")
                fuzzy_match = False if tmdbid else True
            if note:
                note_info = self.__parse_rss_desc(note)
            else:
                note_info = {}
            ret_dict[str(rss_tv.ID)] = {
                "id": rss_tv.ID,
                "name": rss_tv.NAME,
                "year": rss_tv.YEAR,
                "season": rss_tv.SEASON,
                "tmdbid": rss_tv.TMDBID,
                "image": rss_tv.IMAGE,
                "overview": rss_tv.DESC,
                "rss_sites": rss_sites,
                "search_sites": search_sites,
                "over_edition": over_edition,
                "filter_restype": filter_restype,
                "filter_pix": filter_pix,
                "filter_team": filter_team,
                "filter_rule": filter_rule,
                "save_path": save_path,
                "download_setting": download_setting,
                "total": rss_tv.TOTAL,
                "lack": rss_tv.LACK,
                "total_ep": total_ep,
                "current_ep": current_ep,
                "fuzzy_match": fuzzy_match,
                "state": rss_tv.STATE,
                "poster": note_info.get("poster"),
                "release_date": note_info.get("release_date"),
                "vote": note_info.get("vote")
            }
        return ret_dict

    @staticmethod
    def __parse_rss_desc(desc):
        """
        解析订阅的JSON字段
        """
        if not desc:
            return {}
        return json.loads(desc) or {}

    @staticmethod
    def gen_rss_note(media):
        """
        生成订阅的JSON备注信息
        :param media: 媒体信息
        :return: 备注信息
        """
        if not media:
            return {}
        note = {
            "poster": media.get_poster_image(),
            "release_date": media.release_date,
            "vote": media.vote_average
        }
        return json.dumps(note)

    def refresh_rss_metainfo(self):
        """
        定时将豆瓣订阅转换为TMDB的订阅，并更新订阅的TMDB信息
        """
        # 更新电影
        log.info("【Subscribe】开始刷新订阅TMDB信息...")
        rss_movies = self.get_subscribe_movies(state='R')
        for rid, rss_info in rss_movies.items():
            # 跳过模糊匹配的
            if rss_info.get("fuzzy_match"):
                continue
            rssid = rss_info.get("id")
            name = rss_info.get("name")
            year = rss_info.get("year") or ""
            tmdbid = rss_info.get("tmdbid")
            # 更新TMDB信息
            media_info = self.__get_media_info(tmdbid=tmdbid,
                                               name=name,
                                               year=year,
                                               mtype=MediaType.MOVIE,
                                               cache=False)
            if media_info and media_info.tmdb_id and media_info.title != name:
                log.info(f"【Subscribe】检测到TMDB信息变化，更新电影订阅 {name} 为 {media_info.title}")
                # 更新订阅信息
                self.dbhelper.update_rss_movie_tmdb(rid=rssid,
                                                    tmdbid=media_info.tmdb_id,
                                                    title=media_info.title,
                                                    year=media_info.year,
                                                    image=media_info.get_message_image(),
                                                    desc=media_info.overview,
                                                    note=self.gen_rss_note(media_info))
                # 清除TMDB缓存
                self.metahelper.delete_meta_data_by_tmdbid(media_info.tmdb_id)

        # 更新电视剧
        rss_tvs = self.get_subscribe_tvs(state='R')
        for rid, rss_info in rss_tvs.items():
            # 跳过模糊匹配的
            if rss_info.get("fuzzy_match"):
                continue
            rssid = rss_info.get("id")
            name = rss_info.get("name")
            year = rss_info.get("year") or ""
            tmdbid = rss_info.get("tmdbid")
            season = rss_info.get("season") or 1
            total = rss_info.get("total")
            total_ep = rss_info.get("total_ep")
            lack = rss_info.get("lack")
            # 更新TMDB信息
            media_info = self.__get_media_info(tmdbid=tmdbid,
                                               name=name,
                                               year=year,
                                               mtype=MediaType.TV,
                                               cache=False)
            if media_info and media_info.tmdb_id:
                # 获取总集数
                total_episode = self.media.get_tmdb_season_episodes_num(sea=int(str(season).replace("S", "")),
                                                                        tv_info=media_info.tmdb_info)
                # 设置总集数的，不更新集数
                if total_ep:
                    total_episode = total_ep
                if total_episode and (name != media_info.title or total != total_episode):
                    # 新的缺失集数
                    lack_episode = total_episode - (total - lack)
                    log.info(
                        f"【Subscribe】检测到TMDB信息变化，更新电视剧订阅 {name} 为 {media_info.title}，总集数为：{total_episode}")
                    # 更新订阅信息
                    self.dbhelper.update_rss_tv_tmdb(rid=rssid,
                                                     tmdbid=media_info.tmdb_id,
                                                     title=media_info.title,
                                                     year=media_info.year,
                                                     total=total_episode,
                                                     lack=lack_episode,
                                                     image=media_info.get_message_image(),
                                                     desc=media_info.overview,
                                                     note=self.gen_rss_note(media_info))
                    # 清除TMDB缓存
                    self.metahelper.delete_meta_data_by_tmdbid(media_info.tmdb_id)
        log.info("【Subscribe】订阅TMDB信息刷新完成")

    @staticmethod
    def __get_media_info(tmdbid, name, year, mtype, cache=True):
        """
        综合返回媒体信息
        """
        if tmdbid and not tmdbid.startswith("DB:"):
            media_info = MetaInfo(title="%s %s".strip() % (name, year))
            tmdb_info = Media().get_tmdb_info(mtype=mtype, tmdbid=tmdbid)
            media_info.set_tmdb_info(tmdb_info)
        else:
            media_info = Media().get_media_info(title="%s %s" % (name, year), mtype=mtype, strict=True, cache=cache)
        return media_info

    def subscribe_search_all(self):
        """
        搜索R状态的所有订阅，由定时服务调用
        """
        self.subscribe_search(state="R")

    def subscribe_search(self, state="D"):
        """
        RSS订阅队列中状态的任务处理，先进行存量资源检索，缺失的才标志为RSS状态，由定时服务调用
        """
        try:
            lock.acquire()
            # 处理电影
            self.subscribe_search_movie(state=state)
            # 处理电视剧
            self.subscribe_search_tv(state=state)
        finally:
            lock.release()

    def subscribe_search_movie(self, rssid=None, state='D'):
        """
        检索电影RSS
        :param rssid: 订阅ID，未输入时检索所有状态为D的，输入时检索该ID任何状态的
        :param state: 检索的状态，默认为队列中才检索
        """
        if rssid:
            rss_movies = self.get_subscribe_movies(rid=rssid)
        else:
            rss_movies = self.get_subscribe_movies(state=state)
        if rss_movies:
            log.info("【Subscribe】共有 %s 个电影订阅需要检索" % len(rss_movies))
        for rid, rss_info in rss_movies.items():
            # 跳过模糊匹配的
            if rss_info.get("fuzzy_match"):
                continue
            # 搜索站点范围
            rssid = rss_info.get("id")
            name = rss_info.get("name")
            year = rss_info.get("year") or ""
            tmdbid = rss_info.get("tmdbid")

            # 开始搜索
            self.dbhelper.update_rss_movie_state(rssid=rssid, state='S')
            # 识别
            media_info = self.__get_media_info(tmdbid, name, year, MediaType.MOVIE)
            # 未识别到媒体信息
            if not media_info or not media_info.tmdb_info:
                self.dbhelper.update_rss_movie_state(rssid=rssid, state='R')
                continue
            media_info.set_download_info(download_setting=rss_info.get("download_setting"),
                                         save_path=rss_info.get("save_path"))
            # 非洗版的情况检查是否存在
            if not rss_info.get("over_edition"):
                # 检查是否存在
                exist_flag, no_exists, _ = self.downloader.check_exists_medias(meta_info=media_info)
                # 已经存在
                if exist_flag:
                    log.info("【Subscribe】电影 %s 已存在，删除订阅..." % name)
                    self.finish_rss_subscribe(rtype="MOV", rssid=rssid, media=media_info)
                    continue
            else:
                # 洗版时按缺失来下载
                no_exists = {}
            # 开始检索
            filter_dict = {
                "restype": rss_info.get('filter_restype'),
                "pix": rss_info.get('filter_pix'),
                "team": rss_info.get('filter_team'),
                "rule": rss_info.get('filter_rule'),
                "site": rss_info.get("search_sites")
            }
            search_result, no_exists, search_count, download_count = self.searcher.search_one_media(
                media_info=media_info,
                in_from=SearchType.RSS,
                no_exists=no_exists,
                sites=rss_info.get("search_sites"),
                filters=filter_dict)
            if search_result:
                log.info("【Subscribe】电影 %s 下载完成，删除订阅..." % name)
                self.finish_rss_subscribe(rtype="MOV", rssid=rssid, media=media_info)
            else:
                self.dbhelper.update_rss_movie_state(rssid=rssid, state='R')

    def subscribe_search_tv(self, rssid=None, state="D"):
        """
        检索电视剧RSS
        :param rssid: 订阅ID，未输入时检索所有状态为D的，输入时检索该ID任何状态的
        :param state: 检索的状态，默认为队列中才检索
        """
        if rssid:
            rss_tvs = self.get_subscribe_tvs(rid=rssid)
        else:
            rss_tvs = self.get_subscribe_tvs(state=state)
        if rss_tvs:
            log.info("【Subscribe】共有 %s 个电视剧订阅需要检索" % len(rss_tvs))
        rss_no_exists = {}
        for rid, rss_info in rss_tvs.items():
            # 跳过模糊匹配的
            if rss_info.get("fuzzy_match"):
                continue
            rssid = rss_info.get("id")
            name = rss_info.get("name")
            year = rss_info.get("year") or ""
            tmdbid = rss_info.get("tmdbid")
            # 开始搜索
            self.dbhelper.update_rss_tv_state(rssid=rssid, state='S')
            # 识别
            media_info = self.__get_media_info(tmdbid, name, year, MediaType.TV)
            # 未识别到媒体信息
            if not media_info or not media_info.tmdb_info:
                self.dbhelper.update_rss_tv_state(rssid=rssid, state='R')
                continue
            # 取下载设置
            media_info.set_download_info(download_setting=rss_info.get("download_setting"),
                                         save_path=rss_info.get("save_path"))
            # 从登记薄中获取缺失剧集
            season = 1
            if rss_info.get("season"):
                season = int(str(rss_info.get("season")).replace("S", ""))
            # 订阅季
            media_info.begin_season = season
            # 自定义集数
            total_ep = rss_info.get("total")
            current_ep = rss_info.get("current_ep")
            # 表中记录的剩余订阅集数
            episodes = self.dbhelper.get_rss_tv_episodes(rss_info.get("id"))
            if episodes is None:
                episodes = []
                if current_ep:
                    episodes = list(range(current_ep, total_ep + 1))
                rss_no_exists[media_info.tmdb_id] = [
                    {"season": season,
                     "episodes": episodes,
                     "total_episodes": total_ep}]
            elif episodes:
                rss_no_exists[media_info.tmdb_id] = [
                    {"season": season,
                     "episodes": episodes,
                     "total_episodes": total_ep}]
            else:
                log.info("【Subscribe】电视剧 %s%s 已全部订阅完成，删除订阅..." % (
                    media_info.title, media_info.get_season_string()))
                # 完成订阅
                self.finish_rss_subscribe(rtype="TV",
                                          rssid=rss_info.get("id"),
                                          media=media_info)
                continue
            # 非洗版时检查本地媒体库情况
            if not rss_info.get("over_edition"):
                exist_flag, library_no_exists, _ = self.downloader.check_exists_medias(
                    meta_info=media_info,
                    total_ep={season: total_ep})
                # 当前剧集已存在，跳过
                if exist_flag:
                    # 已全部存在
                    if not library_no_exists or not library_no_exists.get(
                            media_info.tmdb_id):
                        log.info("【Subscribe】电视剧 %s 订阅剧集已全部存在，删除订阅..." % (
                            media_info.get_title_string()))
                        # 完成订阅
                        self.finish_rss_subscribe(rtype="TV",
                                                  rssid=rss_info.get("id"),
                                                  media=media_info)
                    continue
                # 取交集做为缺失集
                rss_no_exists = self.media.get_intersection_episodes(target=rss_no_exists,
                                                                     source=library_no_exists,
                                                                     title=media_info.tmdb_id)
                if rss_no_exists.get(media_info.tmdb_id):
                    log.info("【Subscribe】%s 订阅缺失季集：%s" % (
                        media_info.get_title_string(),
                        rss_no_exists.get(media_info.tmdb_id)))

            # 开始检索
            filter_dict = {
                "restype": rss_info.get('filter_restype'),
                "pix": rss_info.get('filter_pix'),
                "team": rss_info.get('filter_team'),
                "rule": rss_info.get('filter_rule'),
                "site": rss_info.get("search_sites")
            }
            search_result, no_exists, search_count, download_count = self.searcher.search_one_media(
                media_info=media_info,
                in_from=SearchType.RSS,
                no_exists=rss_no_exists,
                sites=rss_info.get("search_sites"),
                filters=filter_dict)
            if not no_exists or not no_exists.get(media_info.tmdb_id):
                # 没有剩余或者剩余缺失季集中没有当前标题，说明下完了
                log.info("【Subscribe】电视剧 %s 下载完成，删除订阅..." % name)
                # 完成订阅
                self.finish_rss_subscribe(rtype="TV", rssid=rssid, media=media_info)
            else:
                # 更新状态
                self.dbhelper.update_rss_tv_state(rssid=rssid, state='R')
                no_exist_items = no_exists.get(media_info.tmdb_id)
                for no_exist_item in no_exist_items:
                    if str(no_exist_item.get("season")) == media_info.get_season_seq():
                        if no_exist_item.get("episodes"):
                            log.info("【Subscribe】更新电视剧 %s %s 缺失集数为 %s" % (
                                media_info.get_title_string(), media_info.get_season_string(),
                                len(no_exist_item.get("episodes"))))
                            self.dbhelper.update_rss_tv_lack(rssid=rssid, lack_episodes=no_exist_item.get("episodes"))
                        break
